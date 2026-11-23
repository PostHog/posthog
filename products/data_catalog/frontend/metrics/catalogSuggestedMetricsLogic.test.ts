import { router } from 'kea-router'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { metricsLogic } from '../metricsLogic'
import { usageLogic } from '../usageLogic'
import { catalogMetricsLogic } from './catalogMetricsLogic'
import { catalogSuggestedMetricsLogic } from './catalogSuggestedMetricsLogic'

const proposal = (name: string, description: string): Record<string, unknown> => ({
    name,
    description,
    definition: 'SELECT count() FROM events',
    measures: 1,
    people: 3,
    views: 4,
    complexity: 1,
    built: 5,
    charts: [],
    other_charts: 0,
    surfaces: [],
    agents: null,
})

const SCAN = {
    id: 'scan',
    status: 'done',
    payload: {
        proposed_metrics: [
            proposal('purchase_revenue', 'Total purchase amount across all customers.'),
            proposal('trial_starts', 'How many teams start a trial.'),
        ],
        uncovered: [],
        failed_sections: [],
    },
}

const SHOWN_EVENT = 'data catalog suggested metrics shown'

describe('catalogSuggestedMetricsLogic', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': { results: [], next: null },
                '/api/projects/:team_id/data_quality_checks/': { results: [] },
                '/api/projects/:team_id/data_quality_checks/health/': [],
                '/api/projects/:team_id/data_catalog/usage/': [],
                '/api/projects/:team_id/data_catalog/usage/latest/': SCAN,
            },
        })
        initKeaTests()
        catalogMetricsLogic.mount()
    })

    it('narrows the suggestions with the search and hides them behind a filter of the Metrics tab', async () => {
        const logic = catalogSuggestedMetricsLogic()
        logic.mount()
        await expectLogic(usageLogic).toFinishAllListeners()
        expect(logic.values.visibleSuggestions.map((row) => row.name)).toEqual(['purchase_revenue', 'trial_starts'])

        metricsLogic.actions.setFilters({ search: 'revenue' })

        expect(logic.values.visibleSuggestions.map((row) => row.name)).toEqual(['purchase_revenue'])

        metricsLogic.actions.setFilters({ status: 'proposed' })

        expect(logic.values.visibleSuggestions).toEqual([])
    })

    it('reports the suggestions one time, and only after the tab shows them', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        const shownReports = (): unknown[][] => capture.mock.calls.filter(([event]) => event === SHOWN_EVENT)
        metricsLogic.actions.setFilters({ status: 'proposed' })
        catalogSuggestedMetricsLogic.mount()
        await expectLogic(usageLogic).toFinishAllListeners()
        expect(shownReports()).toEqual([])

        metricsLogic.actions.setFilters({ status: 'all' })
        metricsLogic.actions.setFilters({ search: 'revenue' })

        expect(shownReports()).toEqual([[SHOWN_EVENT, { count: 2 }]])
    })

    it('clears the search and the filters for the link that opens the suggestions', async () => {
        metricsLogic.actions.setFilters({ search: 'no such metric', status: 'proposed' })
        catalogMetricsLogic.actions.setChecksFilter('with')
        router.actions.push('/data-catalog', { tab: 'metrics', filter: 'suggested' })
        const logic = catalogSuggestedMetricsLogic()
        logic.mount()
        await expectLogic(usageLogic).toFinishAllListeners()

        expect(router.values.searchParams).toEqual({ tab: 'metrics' })
        expect(logic.values.visibleSuggestions.map((row) => row.name)).toEqual(['purchase_revenue', 'trial_starts'])
    })
})
