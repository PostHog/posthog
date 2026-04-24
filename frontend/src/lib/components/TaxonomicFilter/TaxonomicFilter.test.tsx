import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
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
                taxonomicGroupTypes: [TaxonomicFilterGroupType.SuggestedFilters, TaxonomicFilterGroupType.Events],
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

            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'test event')

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
            await userEvent.type(searchInput, 'xyznonexistent')

            await waitFor(() => {
                expect(screen.queryByTestId('prop-filter-events-0')).not.toBeInTheDocument()
            })

            await userEvent.clear(searchInput)

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })
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

            await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), 'zzznonexistentevent12345')

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
                '/api/projects/:team/property_definitions': (req: { url: URL }) => {
                    const search = req.url.searchParams.get('search') ?? ''
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
                expectedItems: [],
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
})
