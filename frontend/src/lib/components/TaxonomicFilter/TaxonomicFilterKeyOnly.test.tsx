import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { recentTaxonomicFiltersLogic } from './recentTaxonomicFiltersLogic'
import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from './types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicFilter selectingKeyOnly mode', () => {
    let recents: ReturnType<typeof recentTaxonomicFiltersLogic.build>

    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [] },
                '/api/environments/:team/persons/properties': [{ id: 1, name: 'location', count: 1 }],
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        actionsModel.mount()
        groupsModel.mount()
        recents = recentTaxonomicFiltersLogic.build()
        recents.mount()
    })

    afterEach(() => {
        recents.unmount()
        cleanup()
    })

    function renderFilter(
        props: Partial<React.ComponentProps<typeof TaxonomicFilter>> = {}
    ): ReturnType<typeof render> {
        return render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    onChange={jest.fn()}
                    {...props}
                />
            </Provider>
        )
    }

    function preloadCompleteRecent(key: string, value: string): void {
        recents.actions.recordRecentFilter({
            groupType: TaxonomicFilterGroupType.EventProperties,
            groupName: 'Event properties',
            value: key,
            item: { name: key },
            propertyFilter: { type: PropertyFilterType.Event, key, operator: PropertyOperator.Exact, value },
        })
    }

    describe('recording on selection', () => {
        it('records an EventProperty selection to recents when selectingKeyOnly is set', async () => {
            renderFilter({ selectingKeyOnly: true })

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-event_properties-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-event_properties-0'))

            await waitFor(() => {
                expect(recents.values.recentFilters).toHaveLength(1)
            })
            const [stored] = recents.values.recentFilters
            expect(stored.groupType).toBe(TaxonomicFilterGroupType.EventProperties)
            expect(stored.propertyFilter).toBeUndefined()
        })

        it('does NOT record an EventProperty selection to recents in default (non-selectingKeyOnly) mode', async () => {
            const recordSpy = jest.spyOn(recents.actions, 'recordRecentFilter')
            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-event_properties-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-event_properties-0'))

            // The recorder fires inside a setTimeout(0); flush macrotasks then assert.
            // In non-selectingKeyOnly mode the listener short-circuits for property groups (propertyFilterLogic
            // owns the recording when the filter completes), so the action must never be dispatched.
            await new Promise((r) => setTimeout(r, 0))
            expect(recordSpy).not.toHaveBeenCalled()
            expect(recents.values.recentFilters).toHaveLength(0)
        })

        it('does not carry over an existing complete propertyFilter when re-selecting a recent in selectingKeyOnly mode', async () => {
            preloadCompleteRecent('$browser', 'Chrome')
            const onChange = jest.fn()

            renderFilter({ selectingKeyOnly: true, onChange })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('prop-filter-recent_filters-0'))

            // Consumer-facing onChange must hand back an item whose recent context has no
            // propertyFilter, so it can't accidentally re-apply "= Chrome" downstream.
            await waitFor(() => {
                expect(onChange).toHaveBeenCalled()
            })
            const [, value, item] = onChange.mock.calls[0]
            expect(value).toBe('$browser')
            expect(item?._recentContext?.propertyFilter).toBeUndefined()

            await waitFor(() => {
                // The original complete record stays; a new key-only record is added on top.
                expect(recents.values.recentFilters).toHaveLength(2)
            })
            expect(recents.values.recentFilters[0].propertyFilter).toBeUndefined()
            expect(recents.values.recentFilters[1].propertyFilter).toMatchObject({
                key: '$browser',
                value: 'Chrome',
            })
        })
    })

    describe('display of recents', () => {
        it('shows the Recent tab in selectingKeyOnly mode when key-only recents exist for the picked group', async () => {
            recents.actions.recordRecentFilter({
                groupType: TaxonomicFilterGroupType.EventProperties,
                groupName: 'Event properties',
                value: '$os',
                item: { name: '$os' },
                selectingKeyOnly: true,
            })

            renderFilter({ selectingKeyOnly: true })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })
            const row = screen.getByTestId('prop-filter-recent_filters-0')
            expect(row.textContent).toMatch(/OS/)
            expect(row.textContent).not.toMatch(/=|equals/i)
        })

        it('renders complete recents stripped to just the key in selectingKeyOnly mode', async () => {
            preloadCompleteRecent('$browser', 'Chrome')

            renderFilter({ selectingKeyOnly: true })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })
            const row = screen.getByTestId('prop-filter-recent_filters-0')
            expect(row.textContent).toMatch(/Browser/)
            // The complete-filter label ("Browser equals Chrome") must NOT be rendered.
            expect(row.textContent).not.toMatch(/Chrome/)
        })

        it('renders complete recents WITH their value label in default (non-selectingKeyOnly) mode', async () => {
            preloadCompleteRecent('$browser', 'Chrome')

            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })
            expect(screen.getByTestId('prop-filter-recent_filters-0').textContent).toMatch(/Chrome/)
        })

        it('dedups multiple complete recents for the same key into one row in selectingKeyOnly mode', async () => {
            preloadCompleteRecent('$browser', 'Chrome')
            preloadCompleteRecent('$browser', 'Safari')

            renderFilter({ selectingKeyOnly: true })

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })
            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })
            expect(screen.queryByTestId('prop-filter-recent_filters-1')).not.toBeInTheDocument()
        })
    })
})
