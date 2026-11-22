import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { metricsLogic } from '../metricsLogic'
import { usageLogic } from '../usageLogic'
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

describe('catalogSuggestedMetricsLogic', () => {
    it('narrows the suggestions with the search and hides them behind a filter of the Metrics tab', async () => {
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
        const logic = catalogSuggestedMetricsLogic()
        logic.mount()
        await expectLogic(usageLogic).toFinishAllListeners()
        expect(logic.values.visibleSuggestions.map((row) => row.name)).toEqual(['purchase_revenue', 'trial_starts'])

        metricsLogic.actions.setFilters({ search: 'revenue' })

        expect(logic.values.visibleSuggestions.map((row) => row.name)).toEqual(['purchase_revenue'])

        metricsLogic.actions.setFilters({ status: 'proposed' })

        expect(logic.values.visibleSuggestions).toEqual([])
    })
})
