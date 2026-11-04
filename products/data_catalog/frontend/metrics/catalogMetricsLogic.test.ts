import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { metricsLogic } from '../metricsLogic'
import { catalogMetricsLogic } from './catalogMetricsLogic'

const METRICS = [
    { id: 'metric-approved', name: 'active_accounts', display_name: '', status: 'approved', created_at: '2026-09-01' },
    { id: 'metric-proposed', name: 'trial_conversion', display_name: '', status: 'proposed', created_at: '2026-09-02' },
]

const METRIC_CHECK = {
    id: 'check-1',
    name: 'active accounts stay positive',
    subject_type: 'metric',
    subject_uuid: 'metric-approved',
    subject_name: 'active_accounts',
    subject_metric_name: 'active_accounts',
    last_status: 'passed',
}

describe('catalogMetricsLogic', () => {
    let logic: ReturnType<typeof catalogMetricsLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/data_catalog/metrics/': { results: METRICS, next: null },
                '/api/projects/:team_id/data_quality_checks/': { results: [METRIC_CHECK] },
                '/api/projects/:team_id/data_quality_checks/health/': [],
            },
        })
        initKeaTests()
        logic = catalogMetricsLogic()
        logic.mount()
        void metricsLogic.values.allMetrics
        await expectLogic(metricsLogic).toFinishAllListeners()
        await expectLogic(dataQualityOverviewLogic).toFinishAllListeners()
    })

    it('lists proposed metrics first and narrows to the metrics that have checks', () => {
        expect(logic.values.visibleMetrics.map((metric) => metric.id)).toEqual(['metric-proposed', 'metric-approved'])

        logic.actions.setChecksFilter('with')
        expect(logic.values.visibleMetrics.map((metric) => metric.id)).toEqual(['metric-approved'])

        logic.actions.setChecksFilter('without')
        expect(logic.values.visibleMetrics.map((metric) => metric.id)).toEqual(['metric-proposed'])
    })

    it('goes back to the first page when the search changes', () => {
        logic.actions.setPage(2)
        expect(logic.values.page).toBe(2)

        metricsLogic.actions.setFilters({ search: 'trial' })
        expect(logic.values.page).toBe(1)
    })
})
