import { MOCK_TEAM_ID } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { actionsModel } from '~/models/actionsModel'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { mockActionDefinition, mockGetEventDefinitions, mockGetPropertyDefinitions } from '~/test/mocks'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { recentTaxonomicFiltersLogic } from './recentTaxonomicFiltersLogic'
import { TaxonomicFilter } from './TaxonomicFilter'
import { TaxonomicFilterGroupType } from './types'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('TaxonomicFilter', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            get: {
                '/api/projects/:team/event_definitions': mockGetEventDefinitions,
                '/api/projects/:team/property_definitions': mockGetPropertyDefinitions,
                '/api/projects/:team/actions': { results: [mockActionDefinition] },
                '/api/environments/:team/persons/properties': [
                    { id: 1, name: 'location', count: 1 },
                    { id: 2, name: 'role', count: 2 },
                ],
            },
            post: {
                '/api/environments/:team/query': { results: [] },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.TAXONOMIC_FILTER_RECENTS], {
            [FEATURE_FLAGS.TAXONOMIC_FILTER_RECENTS]: true,
        })
        actionsModel.mount()
        groupsModel.mount()
    })

    afterEach(() => {
        cleanup()
    })

    function renderFilter(
        props: Partial<React.ComponentProps<typeof TaxonomicFilter>> = {}
    ): ReturnType<typeof render> & { onChange: jest.Mock } {
        const onChange = jest.fn()
        const result = render(
            <Provider>
                <TaxonomicFilter
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    onChange={onChange}
                    {...props}
                />
            </Provider>
        )
        return { ...result, onChange }
    }

    it('renders search input and loads results from the API', async () => {
        renderFilter()

        expect(screen.getByTestId('taxonomic-filter-searchfield')).toBeInTheDocument()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })
    })

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

    it('clicking a category tab switches the visible results', async () => {
        renderFilter({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions],
        })

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })

        userEvent.click(screen.getByTestId('taxonomic-tab-actions'))

        await waitFor(() => {
            expect(screen.getByText('Action with a moderately long name')).toBeInTheDocument()
        })
    })

    it('clicking a result calls onChange with the correct group, value, and item', async () => {
        const { onChange } = renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
        })

        userEvent.click(screen.getByTestId('prop-filter-events-1'))

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledTimes(1)
        })
        const [group, value, item] = onChange.mock.calls[0]
        expect(group.type).toBe(TaxonomicFilterGroupType.Events)
        expect(value).toBe('event1')
        expect(item.name).toBe('event1')
    })

    it('keyboard-only: type to search, enter to select', async () => {
        const { onChange } = renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
        })

        await userEvent.type(screen.getByTestId('taxonomic-filter-searchfield'), '$click')

        await waitFor(() => {
            expect(screen.getAllByText('$click').length).toBeGreaterThanOrEqual(1)
        })

        await userEvent.keyboard('{Enter}')

        await waitFor(() => {
            expect(onChange).toHaveBeenCalledTimes(1)
        })

        expect(onChange.mock.calls[0][1]).toBe('event1')
    })

    it('selecting an event records it to recent filters', async () => {
        renderFilter()

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-events-1')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByTestId('prop-filter-events-1'))

        await waitFor(() => {
            const recents = recentTaxonomicFiltersLogic.values.recentFilters
            expect(recents).toHaveLength(1)
            expect(recents[0].groupType).toBe(TaxonomicFilterGroupType.Events)
            expect(recents[0].value).toBe('event1')
        })
    })

    it('selecting an event property does not record to recent filters (deferred to setFilter)', async () => {
        renderFilter({
            taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
        })

        await waitFor(() => {
            expect(screen.getByTestId('prop-filter-event_properties-0')).toBeInTheDocument()
        })

        await userEvent.click(screen.getByTestId('prop-filter-event_properties-0'))

        expect(recentTaxonomicFiltersLogic.values.recentFilters).toHaveLength(0)
    })

    describe('Recent filters tab', () => {
        beforeEach(() => {
            localStorage.clear()
        })

        afterEach(() => {
            if (recentTaxonomicFiltersLogic.isMounted()) {
                recentTaxonomicFiltersLogic.unmount()
            }
        })

        it('auto-appears when there are matching recent items', async () => {
            recentTaxonomicFiltersLogic.mount()
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.Events,
                'event1',
                { name: 'event1', id: 'uuid-1' },
                MOCK_TEAM_ID
            )

            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('taxonomic-tab-recent_filters')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })
        })

        it('only shows items whose group type matches the current context', async () => {
            recentTaxonomicFiltersLogic.mount()
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.Events,
                '$pageview',
                { name: '$pageview', id: 'uuid-pv' },
                MOCK_TEAM_ID
            )
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.PersonProperties,
                'location',
                { name: 'location', id: 'uuid-loc' },
                MOCK_TEAM_ID
            )

            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.PersonProperties],
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })

            expect(screen.queryByText('$pageview')).not.toBeInTheDocument()
        })

        it('does not appear when there are no matching recent items', async () => {
            recentTaxonomicFiltersLogic.mount()

            renderFilter()

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-events-0')).toBeInTheDocument()
            })

            expect(screen.queryByTestId('taxonomic-tab-recent_filters')).not.toBeInTheDocument()
        })

        it('shows a group badge on recent property filter items', async () => {
            recentTaxonomicFiltersLogic.mount()
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.EventProperties,
                '$browser',
                { name: '$browser' },
                MOCK_TEAM_ID,
                {
                    key: '$browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                }
            )

            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })

            const row = screen.getByTestId('prop-filter-recent_filters-0')
            expect(row).toHaveTextContent('Event properties')
        })

        it('renders recent property filter items with the full filter expression', async () => {
            recentTaxonomicFiltersLogic.mount()
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.EventProperties,
                '$browser',
                { name: '$browser' },
                MOCK_TEAM_ID,
                {
                    key: '$browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                }
            )

            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })

            const row = screen.getByTestId('prop-filter-recent_filters-0')
            expect(row).toHaveTextContent('Browser = Chrome')
        })

        it('calls onChange with the recent filter group when clicking a recent property filter', async () => {
            recentTaxonomicFiltersLogic.mount()
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.EventProperties,
                '$browser',
                { name: '$browser' },
                MOCK_TEAM_ID,
                {
                    key: '$browser',
                    value: 'Chrome',
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Event,
                }
            )

            const { onChange } = renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.EventProperties],
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })

            await userEvent.click(screen.getByTestId('prop-filter-recent_filters-0'))

            await waitFor(() => {
                expect(onChange).toHaveBeenCalledTimes(1)
            })

            const [group, , item] = onChange.mock.calls[0]
            expect(group.type).toBe(TaxonomicFilterGroupType.EventProperties)
            expect(item._recentPropertyFilter).toBeUndefined()
            expect(item.group).toBeUndefined()
            expect(item.name).toBe('$browser')
        })

        it('shows a group badge on recent event items too', async () => {
            recentTaxonomicFiltersLogic.mount()
            recentTaxonomicFiltersLogic.actions.recordRecentFilter(
                TaxonomicFilterGroupType.Events,
                'event1',
                { name: 'event1', id: 'uuid-1' },
                MOCK_TEAM_ID
            )

            renderFilter({
                taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
            })

            await userEvent.click(screen.getByTestId('taxonomic-tab-recent_filters'))

            await waitFor(() => {
                expect(screen.getByTestId('prop-filter-recent_filters-0')).toBeInTheDocument()
            })

            const row = screen.getByTestId('prop-filter-recent_filters-0')
            expect(row).toHaveTextContent('event1')
            expect(row).toHaveTextContent('Events')
        })
    })
})
