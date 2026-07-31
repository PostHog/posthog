import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { MockResolverInfo } from '~/mocks/utils'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { performQuery } from '~/queries/query'
import { initKeaTests } from '~/test/init'
import {
    mockActionDefinition,
    mockEventPropertyDefinition,
    mockGetEventDefinitions,
    mockGetPropertyDefinitions,
} from '~/test/mocks'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { recentTaxonomicFiltersLogic } from './recentTaxonomicFiltersLogic'
import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from './types'

jest.mock('~/queries/query', () => ({
    performQuery: jest.fn(),
}))

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicFilter', () => {
    let onChangeMock: jest.Mock
    let onCloseMock: jest.Mock

    beforeEach(() => {
        onChangeMock = jest.fn()
        onCloseMock = jest.fn()
        ;(performQuery as jest.Mock).mockResolvedValue({
            tables: {},
            joins: [],
        })
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [mockActionDefinition] },
                '/api/environments/:team/persons/properties': [
                    { id: 1, name: 'location', count: 1 },
                    { id: 2, name: 'role', count: 2 },
                    { id: 3, name: 'height', count: 3 },
                ],
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        // Recents/pinned persist to localStorage; clear so an earlier test's selection
        // (which records a recent) can't leak in and reorder a later single-group list.
        localStorage.clear()
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderFilter(
        props: Partial<React.ComponentProps<typeof TaxonomicFilter>> = {}
    ): ReturnType<typeof render> {
        return render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    onChange={onChangeMock}
                    onClose={onCloseMock}
                    {...props}
                />
            </Provider>
        )
    }

    function expectActiveTab(activeTestId: string, inactiveTestId?: string): void {
        expect(screen.getByTestId(activeTestId)).toHaveClass('LemonTag--primary')
        if (inactiveTestId) {
            expect(screen.getByTestId(inactiveTestId)).not.toHaveClass('LemonTag--primary')
        }
    }

    // Search interactions pay taxonomicFilterLogic's real 500ms breakpoint (plus stacked
    // 100ms ones), which is what pushed these tests over CI's per-test timeout. Fake timers
    // skip that wait; real timers resume immediately after so the resulting MSW round trip
    // (and any waitFor built on it) settles normally instead of fighting fake-timer polling.
    async function withoutDebounceDelay(
        action: (user: ReturnType<typeof userEvent.setup>) => Promise<void>
    ): Promise<void> {
        // setImmediate also drives MSW v2's response-body pump (like queueMicrotask, see
        // jest.config.ts) — faking it makes advanceTimersByTime re-run that pump once per
        // virtual ms for every matched row, turning a fast search into a slow one.
        jest.useFakeTimers({ doNotFake: ['queueMicrotask', 'setImmediate'] })
        try {
            await action(userEvent.setup({ advanceTimers: jest.advanceTimersByTime }))
            await act(async () => {
                jest.advanceTimersByTime(600)
            })
        } finally {
            jest.useRealTimers()
        }
    }

    describe('rendering', () => {
        it('renders search input and loads results from the API', async () => {
            renderFilter()

            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })
        })

        it('renders category tabs even with one explicit group type due to auto-injected meta groups', async () => {
            renderFilter({ taxonomicGroupTypes: [TaxonomicFilterGroupType.Events] })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            expect(screen.getByText('Categories')).toBeInTheDocument()
        })

        it('renders category tabs when multiple group types are provided', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByText('Categories')).toBeInTheDocument()
            })

            expect(screen.getByTestId('taxonomic-tab-events')).toBeInTheDocument()
            expect(screen.getByTestId('taxonomic-tab-actions')).toBeInTheDocument()
        })

        it.each([
            { label: 'Suggested series', description: 'series context' },
            { label: 'Suggested step', description: 'step context' },
        ])('allows overriding the Suggested filters label with "$label" in $description', async ({ label }) => {
            renderFilter({
                suggestedFiltersLabel: label,
                // Two substantive groups so "All" survives (a single substantive group drops it)
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-suggested_filters')).toHaveTextContent(label)
            })
        })

        it('applies custom width and height via style', async () => {
            const { container } = renderFilter({ width: 500, height: 300 })

            const filterEl = container.querySelector('.taxonomic-filter') as HTMLElement
            expect(filterEl.style.width).toBe('500px')
            expect(filterEl.style.height).toBe('300px')
        })

        it('adds one-taxonomic-tab class when single group type', async () => {
            const { container } = renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
            })

            expect(container.querySelector('.one-taxonomic-tab')).toBeInTheDocument()
        })

        it('does not add one-taxonomic-tab class with multiple group types', async () => {
            const { container } = renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            expect(container.querySelector('.one-taxonomic-tab')).not.toBeInTheDocument()
        })

        it('shows a loading empty state while data warehouse tables are still loading', async () => {
            let resolveQuery: ((value: { tables: Record<string, never>; joins: never[] }) => void) | undefined
            ;(performQuery as jest.Mock).mockImplementation(
                () =>
                    new Promise((resolve) => {
                        resolveQuery = resolve
                    })
            )

            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.DataWarehouse],
            })

            await waitFor(() => {
                expect(screen.getByText('Loading data warehouse tables')).toBeInTheDocument()
            })

            expect(screen.queryByText('Connect external data')).not.toBeInTheDocument()

            resolveQuery?.({ tables: {}, joins: [] })

            await waitFor(() => {
                expect(screen.getByText('Connect external data')).toBeInTheDocument()
            })
        })

        it('shows a loading empty state while data warehouse properties are still loading', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.DataWarehouseProperties],
                schemaColumnsLoading: true,
            })

            await waitFor(() => {
                expect(screen.getByText('Loading data warehouse tables')).toBeInTheDocument()
            })

            expect(screen.queryByText('Connect external data')).not.toBeInTheDocument()
        })
    })

    describe('search', () => {
        it('typing in the search field filters results', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await withoutDebounceDelay((user) =>
                user.type(screen.getByTestId('taxonomic-filter-searchfield'), 'test event')
            )

            await waitFor(() => {
                expect(screen.getAllByText('test event').length).toBeGreaterThanOrEqual(1)
                expect(screen.queryByText('$click')).not.toBeInTheDocument()
            })
        })

        it('shows search placeholder based on active group', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            expect(searchInput).toHaveAttribute('placeholder', expect.stringContaining('Search'))
        })

        it('clears search and calls onClose on escape', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await userEvent.type(searchInput, '$click')

            await waitFor(() => {
                expect(screen.getAllByText('$click').length).toBeGreaterThanOrEqual(1)
            })

            await userEvent.keyboard('{Escape}')

            await waitFor(() => {
                expect(onCloseMock).toHaveBeenCalled()
            })
        })

        it('returns full unfiltered results when search is cleared', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await withoutDebounceDelay((user) => user.type(searchInput, 'xyznonexistent'))

            await waitFor(() => {
                expect(screen.queryByTestId('prop-filter-events-0')).not.toBeInTheDocument()
            })

            await withoutDebounceDelay((user) => user.clear(searchInput))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })
        })
    })

    describe('no results - switch to all', () => {
        // Every group type renders its list (active one visible, the rest hidden via CSS), so the
        // empty-state button can appear in several hidden tabs at once. Scope queries to the visible tab.
        const inVisibleTab = (elements: HTMLElement[]): HTMLElement | undefined =>
            elements.find((el) => !el.closest('.hidden'))

        // Land on a non-"all" group while it still has results, so a later empty search leaves us there
        // (empty tabs aren't clickable, mirroring how a user starts on a group then searches it dry).
        async function activateGroupWithResults(testId: string): Promise<void> {
            await waitFor(() => {
                expect(screen.getByTestId(testId)).not.toHaveAttribute('aria-disabled', 'true')
            })
            await userEvent.click(screen.getByTestId(testId))
        }

        it('offers a button to jump to the all section when another group has matches', async () => {
            renderFilter({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            })

            await activateGroupWithResults('taxonomic-tab-person_properties')
            // Search for something that only matches events, leaving person properties empty.
            // Real timers here: this scenario includes SuggestedFilters, whose reveal-barrier
            // state doesn't survive the fake->real timer switch withoutDebounceDelay performs
            // (a pending fake timer is dropped rather than carried over), so the button never
            // appears. See withoutDebounceDelay's other uses for the debounce-skip that's safe.
            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'test event')

            // The empty state offers a shortcut to the aggregated all/suggested-filters section
            let switchButton: HTMLElement | undefined
            await waitFor(() => {
                switchButton = inVisibleTab(screen.getAllByTestId('taxonomic-switch-to-all'))
                expect(switchButton).toBeTruthy()
            })
            expect(switchButton).toHaveTextContent(/See results from other categories/i)

            await userEvent.click(switchButton!)

            await waitFor(() => {
                expectActiveTab('taxonomic-tab-suggested_filters')
            })
        })

        it('does not offer the button when no other group has matches', async () => {
            renderFilter({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            })

            await activateGroupWithResults('taxonomic-tab-person_properties')
            // Real timers: SuggestedFilters is present here too — see the comment in the
            // preceding test for why withoutDebounceDelay isn't safe for this scenario.
            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'xyznonexistent')

            await waitFor(() => {
                expect(inVisibleTab(screen.getAllByText(/No results for/))).toBeTruthy()
            })
            expect(screen.queryByTestId('taxonomic-switch-to-all')).not.toBeInTheDocument()
        })

        it('offers a per-category jump when matches live on another tab and there is no all section', async () => {
            // No SuggestedFilters group (control variant), so the aggregated "all" jump is unavailable —
            // the empty state must instead point at the specific tab that matched.
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.PersonProperties],
            })

            await activateGroupWithResults('taxonomic-tab-events')
            // `purchase_value` exists only as a property, so the active Events tab comes up empty
            await withoutDebounceDelay((user) =>
                user.type(screen.getByTestId('taxonomic-filter-searchfield'), 'purchase_value')
            )

            let switchButton: HTMLElement | undefined
            await waitFor(() => {
                switchButton = inVisibleTab(screen.getAllByTestId('taxonomic-switch-to-person_properties'))
                expect(switchButton).toBeTruthy()
            })
            expect(switchButton).toHaveTextContent(/See results in Person properties/i)
            expect(screen.queryByTestId('taxonomic-switch-to-all')).not.toBeInTheDocument()

            await userEvent.click(switchButton!)

            await waitFor(() => {
                expectActiveTab('taxonomic-tab-person_properties')
            })
        })

        it('does not offer a jump to a render-backed group with no real matches', async () => {
            // SQL expression is render-backed: its affordance row makes totalListCount non-zero for
            // any query, but it has no actual search results. It must not produce a bogus jump button.
            renderFilter({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.HogQLExpression,
                ],
            })

            await activateGroupWithResults('taxonomic-tab-events')
            await withoutDebounceDelay((user) =>
                user.type(screen.getByTestId('taxonomic-filter-searchfield'), 'purchase_value')
            )

            // The genuinely-matching tab is still offered...
            await waitFor(() => {
                expect(inVisibleTab(screen.getAllByTestId('taxonomic-switch-to-person_properties'))).toBeTruthy()
            })
            // ...but the render-backed SQL expression tab is not.
            expect(screen.queryByTestId('taxonomic-switch-to-hogql_expression')).not.toBeInTheDocument()
        })
    })

    describe('tab switching', () => {
        it('clicking a category tab switches the visible results', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-actions'))

            await waitFor(() => {
                expectActiveTab('taxonomic-tab-actions', 'taxonomic-tab-events')
                expect(screen.getByTestId('prop-filter-actions-0')).toBeInTheDocument()
            })
        })

        it('renders category pills for all provided group types', async () => {
            renderFilter({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                    TaxonomicFilterGroupType.PersonProperties,
                ],
            })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-events')).toBeInTheDocument()
                expect(screen.getByTestId('taxonomic-tab-actions')).toBeInTheDocument()
                expect(screen.getByTestId('taxonomic-tab-person_properties')).toBeInTheDocument()
            })
        })

        it('shows the active tab as primary type', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            expectActiveTab('taxonomic-tab-events')
        })
    })

    describe('item selection', () => {
        it('clicking a result calls onChange with the correct group, value, and item', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-events-1'))

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })
            const [group, value, item] = onChangeMock.mock.calls[0]
            expect(group.type).toBe(TaxonomicFilterGroupType.Events)
            expect(value).toBe('event1')
            expect(item.name).toBe('event1')
        })

        it('selecting an action from the actions tab calls onChange with action group type', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-actions'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-actions-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-actions-0'))

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })
            const [group, value] = onChangeMock.mock.calls[0]
            expect(group.type).toBe(TaxonomicFilterGroupType.Actions)
            expect(value).toBe(3)
        })

        it.each([
            {
                name: 'browse — clicking a row in the events tab with no search query',
                searchQuery: null,
                rowIndex: 1,
                expected: {
                    groupType: TaxonomicFilterGroupType.Events,
                    sourceGroupType: TaxonomicFilterGroupType.Events,
                    wasFromPinnedList: false,
                    wasFromRecents: false,
                    wasQuickFilter: false,
                    hadSearchInput: false,
                    position: 1,
                },
            },
            {
                name: 'search_result — typing a query then clicking the top match',
                searchQuery: 'event',
                rowIndex: 0,
                expected: {
                    groupType: TaxonomicFilterGroupType.Events,
                    sourceGroupType: TaxonomicFilterGroupType.Events,
                    wasFromPinnedList: false,
                    wasFromRecents: false,
                    wasQuickFilter: false,
                    hadSearchInput: true,
                    position: 0,
                },
            },
        ])('captures `taxonomic filter item selected`: $name', async ({ searchQuery, rowIndex, expected }) => {
            const captureSpy = jest.spyOn(posthog, 'capture')
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId(`prop-filter-events-${rowIndex}`)).toBeInTheDocument()
            })

            if (searchQuery) {
                await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), searchQuery)
                await waitFor(() => {
                    expect(screen.getByTestId(`prop-filter-events-${rowIndex}`)).toBeInTheDocument()
                })
            }

            await userEvent.click(screen.getByTestId(`prop-filter-events-${rowIndex}`))

            await waitFor(() => {
                const call = captureSpy.mock.calls.find((c) => c[0] === 'taxonomic filter item selected')
                expect(call).not.toBeUndefined()
                expect(call?.[1]).toMatchObject(expected)
            })
        })

        it('selecting different items in the same group calls onChange each time', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
                expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-events-0'))

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })

            await userEvent.click(screen.getByTestId('prop-filter-events-1'))

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(2)
            })
        })
    })

    describe('`taxonomic filter closed` capture', () => {
        // The TaxonomicFilter logic mounts in many contexts where the picker isn't visibly opened
        // (popovers that render before the popover opens, side panels tied to scene lifecycle...).
        // Without gating, every involuntary mount/unmount fires the close event with
        // hadSelection=false and inflates the abandonment metric. These tests pin the gate.
        it('does not fire when the logic mounts and unmounts with no user interaction', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const { unmount } = renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            unmount()

            const closedCalls = captureSpy.mock.calls.filter((c) => c[0] === 'taxonomic filter closed')
            expect(closedCalls).toHaveLength(0)
        })

        it.each([
            {
                name: 'fires when the user typed in the search input before closing',
                interact: async () => {
                    await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'event')
                },
                expected: { hadSelection: false },
            },
            {
                name: 'fires when the user selected an item before closing',
                interact: async () => {
                    await userEvent.click(screen.getByTestId('prop-filter-events-0'))
                },
                expected: { hadSelection: true },
            },
        ])('$name', async ({ interact, expected }) => {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const { unmount } = renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await interact()

            unmount()

            const closedCall = captureSpy.mock.calls.find((c) => c[0] === 'taxonomic filter closed')
            expect(closedCall).not.toBeUndefined()
            expect(closedCall?.[1]).toMatchObject({
                ...expected,
                dwellMs: expect.any(Number),
                groupType: expect.any(String),
            })
        })
    })

    describe('keyboard navigation', () => {
        it('search narrows results and arrow down + enter selects from filtered list', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), '$click')

            await waitFor(() => {
                expect(screen.queryByTestId('prop-filter-events-1')).not.toBeInTheDocument()
            })

            await userEvent.keyboard('{Enter}')

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })
            expect(onChangeMock.mock.calls[0][1]).toBe('$click')
        })

        it('arrow down moves the highlighted index down', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await userEvent.click(searchInput)

            await userEvent.keyboard('{ArrowDown}')
            await userEvent.keyboard('{ArrowDown}')

            await userEvent.keyboard('{Enter}')

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })
            expect(onChangeMock.mock.calls[0][0].type).toBe(TaxonomicFilterGroupType.Events)
            expect(onChangeMock.mock.calls[0][1]).toBe('test event')
        })

        it('arrow up moves the highlighted index up', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await userEvent.click(searchInput)

            await userEvent.keyboard('{ArrowDown}')
            await userEvent.keyboard('{ArrowDown}')
            await userEvent.keyboard('{ArrowUp}')

            await userEvent.keyboard('{Enter}')

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })
            expect(onChangeMock.mock.calls[0][1]).toBe('event1')
        })

        it('tab key switches to the next category tab', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await userEvent.click(searchInput)

            await userEvent.keyboard('{Tab}')

            await waitFor(() => {
                expectActiveTab('taxonomic-tab-actions', 'taxonomic-tab-events')
                expect(screen.getByTestId('prop-filter-actions-0')).toBeInTheDocument()
            })
        })

        it('shift+tab switches to the previous category tab', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await userEvent.click(searchInput)

            // Tab to actions, then shift+tab back to events
            await userEvent.keyboard('{Tab}')

            await waitFor(() => {
                expectActiveTab('taxonomic-tab-actions')
            })

            await userEvent.keyboard('{Shift>}{Tab}{/Shift}')

            await waitFor(() => {
                expectActiveTab('taxonomic-tab-events', 'taxonomic-tab-actions')
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })
        })
    })

    describe('multiple group types', () => {
        it('events and person properties can be toggled', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.PersonProperties],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-person_properties'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-person_properties-0')).toBeInTheDocument()
            })
        })

        it('displays result counts in category pills', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                const eventsTab = screen.getByTestId('taxonomic-tab-events')
                // The pill shows the group name and a count
                expect(eventsTab.textContent).toContain('Events')
            })
        })
    })

    describe('excluded and selected properties', () => {
        it('excludedProperties filters out specific items from results', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                excludedProperties: {
                    [TaxonomicFilterGroupType.Events]: ['$click'],
                },
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            // $click should be excluded from the list
            const allRows = screen.queryAllByTestId(/^prop-filter-events-/)
            const texts = allRows.map((row) => row.textContent)
            expect(texts.join(' ')).not.toContain('$click')
        })
    })

    describe('search across tabs', () => {
        it('maintains search query when switching between tabs', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            const searchInput = screen.getByTestId('taxonomic-filter-searchfield')
            await userEvent.type(searchInput, 'test')

            await waitFor(() => {
                expect(screen.getAllByText('test event').length).toBeGreaterThanOrEqual(1)
            })

            // Switch tabs - the search field value should persist
            await userEvent.click(screen.getByTestId('taxonomic-tab-actions'))

            expect(searchInput).toHaveValue('test')
        })
    })

    describe('options from props', () => {
        it('renders options provided via optionsFromProp', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Wildcards],
                optionsFromProp: {
                    [TaxonomicFilterGroupType.Wildcards]: [
                        { name: 'custom_wildcard_1' },
                        { name: 'custom_wildcard_2' },
                    ],
                },
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-wildcard-0')).toBeInTheDocument()
            })

            expect(screen.getAllByText('custom_wildcard_1').length).toBeGreaterThanOrEqual(1)
            expect(screen.getAllByText('custom_wildcard_2').length).toBeGreaterThanOrEqual(1)
        })

        it('selecting an option from props calls onChange correctly', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Wildcards],
                optionsFromProp: {
                    [TaxonomicFilterGroupType.Wildcards]: [{ name: 'my_option' }],
                },
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-wildcard-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-wildcard-0'))

            await waitFor(() => {
                expect(onChangeMock).toHaveBeenCalledTimes(1)
            })
            expect(onChangeMock.mock.calls[0][1]).toBe('my_option')
        })
    })

    describe('edge cases', () => {
        it('handles empty API response gracefully', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': () => [200, { results: [], count: 0 }],
                    '/api/projects/:team/property_definitions': () => [200, { results: [], count: 0 }],
                    '/api/projects/:team/actions': { results: [] },
                    '/api/environments/:team/persons/properties': [],
                },
                post: {
                    '/api/environments/:team/query': { results: [] },
                },
            })

            renderFilter()

            expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()
            // Should not crash when no results are returned
        })

        it('renders without onChange callback without errors', async () => {
            expect(() => {
                render(
                    <Provider>
                        <TaxonomicFilter taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]} />
                    </Provider>
                )
            }).not.toThrow()
        })

        it('renders with a pre-selected groupType', async () => {
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                groupType: TaxonomicFilterGroupType.Actions,
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-actions-0')).toBeInTheDocument()
            })
        })

        it('renders correctly when search matches no items', async () => {
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await withoutDebounceDelay((user) =>
                user.type(screen.getByTestId('taxonomic-filter-searchfield'), 'zzznonexistentevent12345')
            )

            await waitFor(() => {
                expect(screen.queryAllByTestId(/^prop-filter-events-/)).toHaveLength(0)
            })
        })
    })

    it.each([
        {
            search: 'url',
            expectedFirstProperty: '$current_url',
            description: 'promotes $current_url for exact search term',
        },
        {
            search: 'urls',
            expectedFirstProperty: '$initial_referring_url',
            description: 'does not promote for near-miss search term',
        },
    ])('$description', async ({ search, expectedFirstProperty }) => {
        // Return $current_url after other url-containing properties so we can
        // verify that promotion moves it to position 0.
        useMocks({
            get: {
                '/api/projects/:team/property_definitions': ({ request }) => {
                    const search = new URL(request.url).searchParams.get('search') ?? ''
                    const allProps = [
                        { ...mockEventPropertyDefinition, id: 'url-other', name: '$initial_referring_url' },
                        { ...mockEventPropertyDefinition, id: 'url-other-2', name: 'signup_url' },
                        { ...mockEventPropertyDefinition, id: 'url-current', name: '$current_url' },
                    ]
                    // Keep near-miss searches returning URL-like properties so we can
                    // assert that only exact promotion terms change ordering.
                    const filterSearch = search === 'urls' ? 'url' : search
                    const results = filterSearch ? allProps.filter((p) => p.name.includes(filterSearch)) : allProps
                    return [200, { results, count: results.length }]
                },
            },
        })

        renderFilter({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
        })

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-event_properties-0')).toBeInTheDocument()
        })

        await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), search)

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-event_properties-0')).toHaveTextContent(
                new RegExp(expectedFirstProperty.replace(/^\$/, '').replace(/_/g, '[ _]'), 'i')
            )
        })

        // Clicking the first result should select the promoted (or unpromoted) first result.
        await userEvent.click(screen.getByTestId('prop-filter-event_properties-0'))

        await waitFor(() => {
            expect(onChangeMock).toHaveBeenCalledTimes(1)
        })
        expect(onChangeMock.mock.calls[0][1]).toBe(expectedFirstProperty)
    })

    describe('replay group selection', () => {
        it.each([
            { label: 'Visited page', expectedKey: 'visited_page', expectedPropertyFilterType: 'recording' },
            { label: 'Platform', expectedKey: 'snapshot_source', expectedPropertyFilterType: 'recording' },
            { label: 'Console log level', expectedKey: 'level', expectedPropertyFilterType: 'log_entry' },
            { label: 'Console log message', expectedKey: 'message', expectedPropertyFilterType: 'log_entry' },
            { label: 'Comment text', expectedKey: 'comment_text', expectedPropertyFilterType: 'recording' },
        ])(
            'selecting "$label" calls onChange with key "$expectedKey" and propertyFilterType "$expectedPropertyFilterType"',
            async ({ label, expectedKey, expectedPropertyFilterType }) => {
                renderFilter({
                    taxonomicGroupTypes: [TaxonomicFilterGroupType.Replay],
                })

                await waitFor(() => {
                    expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1)
                })

                await userEvent.click(screen.getAllByText(label)[0])

                await waitFor(() => {
                    expect(onChangeMock).toHaveBeenCalledTimes(1)
                })
                const [group, value, item] = onChangeMock.mock.calls[0]
                expect(group.type).toBe(TaxonomicFilterGroupType.Replay)
                expect(value).toBe(expectedKey)
                expect(item.propertyFilterType).toBe(expectedPropertyFilterType)
            }
        )
    })

    describe('autocapture context', () => {
        it.each([
            {
                eventNames: ['$autocapture'],
                expectedItems: ['Text', 'CSS selector'],
            },
            {
                eventNames: ['$pageview'],
                // Pageview's taxonomy primary property ($pathname) bubbles up here so the
                // user can filter by the property the team chose to highlight for that event.
                expectedItems: ['Path name'],
            },
        ])(
            'SuggestedFilters shows $expectedItems.length items when eventNames=$eventNames',
            async ({ eventNames, expectedItems }) => {
                renderFilter({
                    eventNames,
                    taxonomicGroupTypes: [
                        TaxonomicFilterGroupType.SuggestedFilters,
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.Elements,
                    ],
                })

                await waitFor(() => {
                    expect(screen.getByTestId('taxonomic-tab-suggested_filters')).toBeInTheDocument()
                })

                if (expectedItems.length > 0) {
                    expectActiveTab('taxonomic-tab-suggested_filters')

                    await waitFor(() => {
                        for (let i = 0; i < expectedItems.length; i++) {
                            const el = screen.getByTestId(`prop-filter-suggested_filters-${i}`)
                            expect(el).toHaveTextContent(expectedItems[i])
                        }
                    })
                } else {
                    expect(screen.queryByTestId('prop-filter-suggested_filters-0')).not.toBeInTheDocument()
                }
            }
        )

        it.each([
            {
                description: 'Elements tab is promoted when eventNames includes $autocapture',
                eventNames: ['$autocapture'],
                expectElementsPromoted: true,
            },
            {
                description: 'Elements tab stays in default position when eventNames does not include $autocapture',
                eventNames: ['$pageview'],
                expectElementsPromoted: false,
            },
        ])('$description', async ({ eventNames, expectElementsPromoted }) => {
            renderFilter({
                eventNames,
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.EventProperties,
                    TaxonomicFilterGroupType.PersonProperties,
                    TaxonomicFilterGroupType.Elements,
                ],
            })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-elements')).toBeInTheDocument()
            })

            const allTabs = screen.getAllByTestId(/^taxonomic-tab-/).map((el) => el.getAttribute('data-attr'))

            const elementsIndex = allTabs.indexOf('taxonomic-tab-elements')
            const eventPropsIndex = allTabs.indexOf('taxonomic-tab-event_properties')

            if (expectElementsPromoted) {
                expect(elementsIndex).toBeLessThan(eventPropsIndex)
            } else {
                expect(elementsIndex).toBeGreaterThan(eventPropsIndex)
            }
        })
    })

    describe('enableKeywordShortcuts', () => {
        it('threads the prop from TaxonomicFilter through to the shortcut row', async () => {
            const user = userEvent.setup()
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
                enableKeywordShortcuts: true,
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await user.type(searchInput, 'click')

            // The shortcut row carries a unique data-attr so the assertion isn't fooled by the
            // definition popover which renders the same label text.
            await waitFor(() => {
                expect(document.querySelector('[data-attr="taxonomic-shortcut-click-series"]')).not.toBeNull()
            })
        })

        it('does not render shortcut rows when enableKeywordShortcuts is omitted', async () => {
            const user = userEvent.setup()
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await user.type(searchInput, 'click')

            // Give the infinite list a moment to settle then assert the row is absent.
            await waitFor(() => expect(searchInput).toHaveValue('click'))
            expect(document.querySelector('[data-attr="taxonomic-shortcut-click-series"]')).toBeNull()
        })
    })

    describe('collapseUrlsToContainsRow', () => {
        function useMockPageviewUrls(urls: string[]): void {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                    '/api/environments/:team/events/values': urls.map((name) => ({ name })),
                },
            })
        }

        it('collapses the matching URL list to a single "URL contains" shortcut row', async () => {
            useMockPageviewUrls(['https://example.com/pricing', 'https://example.com/pricing/teams'])
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls],
                collapseUrlsToContainsRow: true,
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await withoutDebounceDelay((fakeTimerUser) => fakeTimerUser.type(searchInput, 'pricing'))

            const firstRow = await waitFor(() => screen.getByTestId('prop-filter-pageview_urls-0'))
            // The two matching URLs collapse into one row, which is the contains shortcut.
            expect(firstRow.querySelector('[data-attr="taxonomic-shortcut-pricing-property"]')).not.toBeNull()
            expect(screen.queryByTestId('prop-filter-pageview_urls-1')).not.toBeInTheDocument()
        })

        it('commits $current_url IContains <query> when the shortcut row is selected', async () => {
            const user = userEvent.setup()
            useMockPageviewUrls(['https://example.com/pricing'])
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls],
                collapseUrlsToContainsRow: true,
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await withoutDebounceDelay((fakeTimerUser) => fakeTimerUser.type(searchInput, 'pricing'))

            const row = await waitFor(() => {
                const el = document.querySelector('[data-attr="taxonomic-shortcut-pricing-property"]')
                expect(el).not.toBeNull()
                return el as HTMLElement
            })
            await user.click(row)

            expect(onChangeMock).toHaveBeenCalledWith(
                expect.objectContaining({ type: TaxonomicFilterGroupType.PageviewUrls }),
                'pricing',
                expect.objectContaining({
                    _type: 'quick_filter',
                    propertyKey: '$current_url',
                    operator: PropertyOperator.IContains,
                    filterValue: 'pricing',
                    propertyFilterType: PropertyFilterType.Event,
                    // Tagged so commit telemetry can distinguish the URL-contains shortcut
                    // from keyword shortcuts (parity with the rebuild's wasUrlContainsShortcut).
                    isContainsShortcut: true,
                })
            )
        })

        it('collapses URLs in the aggregated Suggested filters tab too', async () => {
            // Real timers: this scenario includes SuggestedFilters, whose reveal-barrier state
            // doesn't survive the fake->real timer switch withoutDebounceDelay performs (a
            // pending fake timer is dropped rather than carried over), so the aggregated row
            // never appears. See withoutDebounceDelay's other uses in this describe for the
            // debounce-skip that's safe when SuggestedFilters isn't part of the group list.
            const user = userEvent.setup()
            useMockPageviewUrls(['https://example.com/pricing', 'https://example.com/pricing/teams'])
            renderFilter({
                // Two substantive groups so the aggregated "All" tab survives (a single
                // substantive group drops it); Events has no 'pricing' match so the URL
                // shortcut is still the only aggregated row.
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.PageviewUrls,
                    TaxonomicFilterGroupType.Events,
                ],
                collapseUrlsToContainsRow: true,
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await user.type(searchInput, 'pricing')

            // The Suggested filters tab is the default and aggregates each group's top matches —
            // the URL group must contribute the single shortcut there, not raw URLs.
            const firstRow = await waitFor(() => screen.getByTestId('prop-filter-suggested_filters-0'))
            expect(firstRow.querySelector('[data-attr="taxonomic-shortcut-pricing-property"]')).not.toBeNull()
            expect(screen.queryByTestId('prop-filter-suggested_filters-1')).not.toBeInTheDocument()
        })

        it('lists individual URLs (no collapse) when the prop is omitted', async () => {
            useMockPageviewUrls(['https://example.com/pricing'])
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls],
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await withoutDebounceDelay((fakeTimerUser) => fakeTimerUser.type(searchInput, 'pricing'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-pageview_urls-0')).toBeInTheDocument()
            })
            expect(document.querySelector('[data-attr="taxonomic-shortcut-pricing-property"]')).toBeNull()
        })

        it('shows no shortcut row when no URL matches the query', async () => {
            // Flag set when the URL values endpoint actually responds (empty), so the negative
            // assertions below aren't vacuously true before the async fetch path runs.
            let valuesFetched = false
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                    '/api/environments/:team/events/values': () => {
                        valuesFetched = true
                        return [200, []]
                    },
                },
            })
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.PageviewUrls],
                collapseUrlsToContainsRow: true,
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            // A query unique to this test so the module-level `apiCache` in infiniteListLogic
            // can't serve a non-empty response cached by an earlier test under the same URL.
            await withoutDebounceDelay((user) => user.type(searchInput, 'nomatchquery'))

            await waitFor(() => expect(valuesFetched).toBe(true))
            await waitFor(() => {
                expect(screen.queryByText('URL contains "nomatchquery"')).not.toBeInTheDocument()
                expect(document.querySelector('[data-attr="taxonomic-shortcut-nomatchquery-property"]')).toBeNull()
            })
        })
    })

    it('reopens on the selected category when no Suggested-filters surface is present (control)', async () => {
        // Guards the activeTab fallback: hosts without a Suggested filters ("All") surface
        // (control variant, or any picker that doesn't inject it) must still reopen on the
        // selected item's own category rather than an absent All tab.
        renderFilter({
            groupType: TaxonomicFilterGroupType.Events,
            value: '$pageview',
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
        })

        await waitFor(() => expect(screen.getByTestId('taxonomic-tab-events')).toBeInTheDocument())
        expectActiveTab('taxonomic-tab-events', 'taxonomic-tab-actions')
    })

    // Spec for the insight series picker in the pill variant: searching a term that matches
    // pageview URLs should make ONE "url contains <query>" shortcut the first row of the
    // aggregated Suggested filters ("All") tab — ahead of raw URL/event rows. Fails today
    // because the series (PageviewEvents) group isn't collapsed and the shortcut never leads.
    describe('series picker: pageview url-contains shortcut leads (pill variant)', () => {
        let unmountFeatureFlagLogic: (() => void) | null = null

        beforeEach(() => {
            unmountFeatureFlagLogic = featureFlagLogic.mount()
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN], {
                [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: 'pill',
            })
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                    '/api/environments/:team/events/values': [
                        { name: 'https://app.posthog.com/replay' },
                        { name: 'https://app.posthog.com/replay/home' },
                    ],
                },
            })
        })

        afterEach(() => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            unmountFeatureFlagLogic?.()
            unmountFeatureFlagLogic = null
        })

        it('reopens on the Data warehouse tab (its own picker), not All, for a data-warehouse selection', async () => {
            renderFilter({
                groupType: TaxonomicFilterGroupType.DataWarehouse,
                value: 'some_table',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.DataWarehouse,
                ],
            })

            // Data warehouse is a config flow (table/column picker) — it should reopen on
            // its own tab so the user can reconfigure, not drop them on the All surface.
            const trigger = await screen.findByTestId('taxonomic-category-dropdown-trigger-pill')
            await waitFor(() => expect(trigger.textContent || '').toMatch(/All|Data warehouse|Events/))
            expect(trigger).toHaveTextContent('Data warehouse')
            expect(trigger).not.toHaveTextContent('All')
        })

        it('opens focused on the All tab, not Events, when an event is already selected', async () => {
            renderFilter({
                groupType: TaxonomicFilterGroupType.Events,
                value: '$pageview',
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            })

            // In the pill variant the active category shows in the dropdown trigger; reopening
            // on an existing event selection should read "All", not "Events".
            const trigger = await screen.findByTestId('taxonomic-category-dropdown-trigger-pill')
            // Wait for the dropdown trigger to paint its active-category label before asserting.
            await waitFor(() => expect(trigger.textContent || '').toMatch(/All|Events|Suggestions/))
            expect(trigger).toHaveTextContent('All')
            expect(trigger).not.toHaveTextContent('Events')
        })

        it('makes the "url contains <query>" shortcut the first Suggested-filters row', async () => {
            const user = userEvent.setup()
            renderFilter({
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.PageviewEvents,
                    TaxonomicFilterGroupType.EventProperties,
                ],
                collapseUrlsToContainsRow: true,
            })

            const searchInput = await waitFor(() => screen.getByTestId('taxonomic-filter-searchfield'))
            await user.type(searchInput, 'replay')

            const firstRow = await waitFor(() => screen.getByTestId('prop-filter-suggested_filters-0'))
            // The leading aggregated row should be the single contains shortcut, not a raw URL.
            expect(firstRow.textContent || '').toMatch(/contains.*replay|replay.*contains/i)
            expect(firstRow.textContent || '').not.toContain('https://app.posthog.com/replay')
        })
    })

    describe('category dropdown A/B test', () => {
        let unmountFeatureFlagLogic: (() => void) | null = null

        beforeEach(() => {
            unmountFeatureFlagLogic = featureFlagLogic.mount()
        })

        afterEach(() => {
            featureFlagLogic.actions.setFeatureFlags([], {})
            unmountFeatureFlagLogic?.()
            unmountFeatureFlagLogic = null
        })

        function setVariant(variant: string): void {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN], {
                [FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]: variant,
            })
        }

        it('control variant: renders the categories column and no in-input affordance', async () => {
            setVariant('control')
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByText('Categories')).toBeInTheDocument()
            })

            expect(screen.queryByTestId(/taxonomic-category-dropdown-trigger-/)).not.toBeInTheDocument()
        })

        it('pill variant with hideSearchInput: does not render the categories column or an in-filter dropdown; the host is expected to render CategoryDropdown inside its own input', async () => {
            setVariant('pill')
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
                hideSearchInput: true,
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            expect(screen.queryByText('Categories')).not.toBeInTheDocument()
            expect(screen.queryByTestId(/taxonomic-category-dropdown-trigger-/)).not.toBeInTheDocument()
        })

        it('control variant: default suggested-filters label is "Suggestions"', async () => {
            setVariant('control')
            renderFilter({
                // Two substantive groups so "All" survives (a single substantive group drops it)
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-suggested_filters')).toHaveTextContent('Suggestions')
            })
        })

        it('pill variant: default suggested-filters label is "All" (seen in the dropdown items)', async () => {
            setVariant('pill')
            renderFilter({
                // Two substantive groups so "All" survives (a single substantive group drops it)
                taxonomicGroupTypes: [
                    TaxonomicFilterGroupType.SuggestedFilters,
                    TaxonomicFilterGroupType.Events,
                    TaxonomicFilterGroupType.Actions,
                ],
            })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-category-dropdown-trigger-pill')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-category-dropdown-trigger-pill'))

            const item = await screen.findByTestId('taxonomic-category-dropdown-item-suggested_filters')
            expect(item).toHaveTextContent('All')
        })

        it('pill variant: hides the categories column and renders the in-input affordance', async () => {
            setVariant('pill')
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-category-dropdown-trigger-pill')).toBeInTheDocument()
            })

            expect(screen.queryByText('Categories')).not.toBeInTheDocument()
        })

        it('pill variant: opening the dropdown and picking a category switches the visible results', async () => {
            setVariant('pill')
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-category-dropdown-trigger-pill'))

            await userEvent.click(await screen.findByTestId('taxonomic-category-dropdown-item-actions'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-actions-0')).toBeInTheDocument()
            })
        })

        it('pill variant: pressing Tab in the search input does not switch category', async () => {
            setVariant('pill')
            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
            })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            // Pill auto-injects the "All" (SuggestedFilters) tab as the default for a
            // multi-group picker, so that's the category showing before and after Tab.
            const trigger = screen.getByTestId('taxonomic-category-dropdown-trigger-pill')
            expect(trigger).toHaveAttribute('aria-label', expect.stringContaining('All'))

            const input = screen.getByTestId('taxonomic-filter-searchfield') as HTMLInputElement
            input.focus()
            await userEvent.keyboard('{Tab}')

            expect(screen.getByTestId('taxonomic-category-dropdown-trigger-pill')).toHaveAttribute(
                'aria-label',
                expect.stringContaining('All')
            )
        })
    })

    describe('promoted properties float to position 0 on search', () => {
        // The API deliberately returns the promoted property *last* (after the decoys)
        // so a passing assertion can only mean promotion reordered it, not the server order.
        // Rows render the property's display label, while the decoys render their raw names.
        const promotedFixtures: Record<string, { label: string; name: string; decoys: string[] }> = {
            url: { label: 'Current URL', name: '$current_url', decoys: ['referrer_url', 'initial_url'] },
            path: { label: 'Path name', name: '$pathname', decoys: ['file_path', 'initial_path'] },
        }

        beforeEach(() => {
            // Recents persist to localStorage across tests; a leftover promoted property
            // from an earlier test would otherwise render before our mock response loads.
            localStorage.clear()
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                    '/api/projects/:team/property_definitions': ({ request }: MockResolverInfo) => {
                        const search = new URL(request.url).searchParams.get('search') ?? ''
                        const fixture = promotedFixtures[search]
                        const names = fixture ? [...fixture.decoys, fixture.name] : []
                        return [
                            200,
                            {
                                results: names.map((name, index) => ({
                                    ...mockEventPropertyDefinition,
                                    id: `promoted-fixture-${index}`,
                                    name,
                                })),
                                count: names.length,
                            },
                        ]
                    },
                    '/api/projects/:team/actions': { results: [] },
                },
                post: {
                    '/api/environments/:team/query': { results: [] },
                },
            })
        })

        const rowIndexFor = (text: string): number =>
            parseInt(
                (Array.from(document.querySelectorAll('[data-attr^="prop-filter-event_properties-"]'))
                    .find((el) => el.textContent?.includes(text))
                    ?.getAttribute('data-attr')
                    ?.split('-')
                    .pop() as string) ?? 'NaN'
            )

        it.each([['url'], ['path']])('searching %p floats the promoted property to row 0', async (searchTerm) => {
            const { label, decoys } = promotedFixtures[searchTerm]
            renderFilter({ taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties] })

            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), searchTerm)

            // Activate the event-properties list so we assert on its rows, not the
            // aggregated Suggested-filters tab that may be active by default.
            await userEvent.click(screen.getByTestId('taxonomic-tab-event_properties'))

            // Wait on a decoy (only present in our mock response) so we assert order
            // after the real fetch rendered, not on a leftover/top-match promoted row.
            await waitFor(() => {
                expect(rowIndexFor(decoys[0])).toBeGreaterThan(-1)
            })

            expect(rowIndexFor(label)).toBe(0)
            // the decoys the API returned first are pushed below the promoted row
            for (const decoy of decoys) {
                expect(rowIndexFor(decoy)).toBeGreaterThan(0)
            }
        })
    })

    describe('log attribute value-match indicator', () => {
        const mockLogAttributes = {
            results: [
                { name: 'service.name', propertyFilterType: 'log_resource_attribute', matchedOn: 'key' },
                { name: 'k8s.pod.name', propertyFilterType: 'log_resource_attribute', matchedOn: 'key' },
                {
                    name: 'k8s.deployment.name',
                    propertyFilterType: 'log_resource_attribute',
                    matchedOn: 'value',
                    matchedValue: 'argo-rollouts-dashboard',
                },
            ],
            count: 3,
        }

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                    '/api/projects/:team/actions': { results: [] },
                    '/api/environments/:team/logs/attributes': mockLogAttributes,
                },
                post: {
                    '/api/environments/:team/query': { results: [] },
                },
            })
        })

        it('renders the value-match indicator only on rows matched by value', async () => {
            renderFilter({ taxonomicGroupTypes: [TaxonomicFilterGroupType.LogResourceAttributes] })

            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'argo')

            await waitFor(() => {
                expect(screen.getByText('k8s.deployment.name')).toBeInTheDocument()
            })

            const indicators = screen.queryAllByLabelText('Matched on value')
            expect(indicators).toHaveLength(1)
            const indicator = indicators[0]
            // Badge shows the (possibly truncated) matched value
            expect(indicator.textContent).toContain('argo-rollouts-dashboard')
            const row = indicator.closest('.taxonomic-list-row, [data-attr*="prop-filter"]') ?? indicator.parentElement
            expect(row?.textContent).toContain('k8s.deployment.name')
            expect(row?.textContent).not.toContain('service.name')
        })

        it('orders key matches above value matches in the rendered list', async () => {
            renderFilter({ taxonomicGroupTypes: [TaxonomicFilterGroupType.LogResourceAttributes] })

            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'argo')

            await waitFor(() => {
                expect(screen.getAllByText('service.name').length).toBeGreaterThan(0)
            })

            // Anchor on the row data-attr so we ignore tooltips / titles that duplicate the text.
            const rowText = (name: string): string =>
                Array.from(document.querySelectorAll('[data-attr^="prop-filter-log_resource_attributes-"]'))
                    .find((el) => el.textContent?.includes(name))
                    ?.getAttribute('data-attr') ?? ''

            const serviceIdx = rowText('service.name')
            const podIdx = rowText('k8s.pod.name')
            const deploymentIdx = rowText('k8s.deployment.name')
            expect(serviceIdx).not.toBe('')
            expect(podIdx).not.toBe('')
            expect(deploymentIdx).not.toBe('')
            // data-attr ends with the row index; key matches (0,1) come before value matches (2)
            expect(parseInt(serviceIdx.split('-').pop() as string)).toBeLessThan(
                parseInt(deploymentIdx.split('-').pop() as string)
            )
            expect(parseInt(podIdx.split('-').pop() as string)).toBeLessThan(
                parseInt(deploymentIdx.split('-').pop() as string)
            )
        })
    })

    describe('excludedOperators', () => {
        const seedRecents = (): void => {
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            recentLogic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Cohorts,
                groupName: 'Cohorts',
                value: 1,
                item: { name: 'Power Users' },
                propertyFilter: {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 1,
                    operator: PropertyOperator.In,
                    cohort_name: 'Power Users',
                },
            })
            recentLogic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Cohorts,
                groupName: 'Cohorts',
                value: 2,
                item: { name: 'Trial Users' },
                propertyFilter: {
                    type: PropertyFilterType.Cohort,
                    key: 'id',
                    value: 2,
                    operator: PropertyOperator.NotIn,
                    cohort_name: 'Trial Users',
                },
            })
            recentLogic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$browser',
                item: { name: '$browser' },
                propertyFilter: {
                    type: PropertyFilterType.Event,
                    key: '$browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                },
            })
        }

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                    '/api/projects/:team/cohorts/': { results: [], next: null, count: 0 },
                    '/api/projects/:team/actions': { results: [] },
                },
                post: {
                    '/api/environments/:team/query': { results: [] },
                },
            })
            localStorage.clear()
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            recentLogic.actions.clearRecentFilters()
            seedRecents()
        })

        it.each([
            {
                name: 'hides cohort recents whose operator is denylisted but keeps other recents',
                excludedOperators: { [TaxonomicFilterGroupType.Cohorts]: [PropertyOperator.NotIn] },
                expectInRecent: ['User in Power Users', 'Browser = Chrome'],
                expectNotInRecent: ['User not in Trial Users'],
            },
            {
                name: 'keeps every recent when no operators are denylisted',
                excludedOperators: undefined,
                expectInRecent: ['User in Power Users', 'User not in Trial Users', 'Browser = Chrome'],
                expectNotInRecent: [],
            },
        ])('$name', async ({ excludedOperators, expectInRecent, expectNotInRecent }) => {
            render(
                <Provider>
                    <TaxonomicFilter
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.Cohorts,
                            TaxonomicFilterGroupType.EventProperties,
                        ]}
                        excludedOperators={excludedOperators}
                        onChange={onChangeMock}
                        onClose={onCloseMock}
                    />
                </Provider>
            )

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            const recentRowText = (): string =>
                Array.from(document.querySelectorAll('[data-attr^="prop-filter-recent_filters-"]'))
                    .map((el) => el.textContent ?? '')
                    .join('||')

            await waitFor(() => {
                for (const expected of expectInRecent) {
                    expect(recentRowText()).toContain(expected)
                }
            })

            const allText = recentRowText()
            for (const forbidden of expectNotInRecent) {
                expect(allText).not.toContain(forbidden)
            }
        })
    })

    describe('reveal barrier and recent matches in SuggestedFilters search', () => {
        // These tests cover the SuggestedFilters tab's two-phase reveal: matching recents
        // surface immediately while every non-meta group renders as a skeleton, then when
        // either every remote group resolves or the 5s timer fires the barrier opens and
        // real results replace the skeletons.
        const seedRecentEvent = (): void => {
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            recentLogic.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.Events,
                groupName: 'Events',
                value: 'onboarding_completed_recent',
                item: { id: 'recent-onboarding', name: 'onboarding_completed_recent' },
            })
        }

        beforeEach(() => {
            localStorage.clear()
            // Slow the events endpoint so the barrier-closed state survives at least one paint
            // — the default mock resolves synchronously, which collapses the close-then-open
            // cycle inside a single React batch, making the transient skeleton state invisible
            // to the DOM in CI. Production latency exceeds this comfortably.
            useMocks({
                get: {
                    '/api/projects/:team/event_definitions': async (info) => {
                        await new Promise((resolve) => setTimeout(resolve, 100))
                        return mockGetEventDefinitions(info)
                    },
                    '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                    '/api/projects/:team/actions': { results: [mockActionDefinition] },
                    '/api/environments/:team/persons/properties': [
                        { id: 1, name: 'location', count: 1 },
                        { id: 2, name: 'role', count: 2 },
                        { id: 3, name: 'height', count: 3 },
                    ],
                },
                post: {
                    '/api/environments/:team/query': { results: [] },
                },
            })
            const recentLogic = recentTaxonomicFiltersLogic.build()
            recentLogic.mount()
            recentLogic.actions.clearRecentFilters()
            seedRecentEvent()
        })

        const renderWithSuggested = (): void => {
            render(
                <Provider>
                    <TaxonomicFilter
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.SuggestedFilters,
                            TaxonomicFilterGroupType.Events,
                            TaxonomicFilterGroupType.Actions,
                        ]}
                        onChange={onChangeMock}
                        onClose={onCloseMock}
                    />
                </Provider>
            )
        }

        const findSuggestedSkeleton = (): Element | null =>
            document.querySelector('[data-attr^="prop-skeleton-suggested_filters-"]')

        it('renders a skeleton row per non-meta group while the reveal barrier is closed, then replaces them with real results', async () => {
            renderWithSuggested()

            const searchField = await screen.findByTestId('taxonomic-filter-searchfield')
            await userEvent.type(searchField, 'event')

            await waitFor(() => {
                if (!findSuggestedSkeleton()) {
                    throw new Error('expected at least one suggested_filters skeleton row')
                }
            })

            const testEventRows = await screen.findAllByText('test event', undefined, { timeout: 6000 })
            expect(testEventRows.length).toBeGreaterThanOrEqual(1)

            await waitFor(
                () => {
                    if (findSuggestedSkeleton()) {
                        throw new Error('expected suggested_filters skeletons to be removed once the barrier opens')
                    }
                },
                { timeout: 6000 }
            )
        }, 10000)

        it('a recent that matches the search appears in the SuggestedFilters list even though the barrier gates other groups', async () => {
            renderWithSuggested()

            const searchField = await screen.findByTestId('taxonomic-filter-searchfield')
            await userEvent.type(searchField, 'onboarding_completed_recent')

            const matches = await screen.findAllByText('onboarding_completed_recent', undefined, { timeout: 6000 })
            expect(matches.length).toBeGreaterThanOrEqual(1)
        }, 10000)
    })
})
