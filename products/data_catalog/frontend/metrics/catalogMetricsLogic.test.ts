import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { dataQualityOverviewLogic } from 'products/data_quality/frontend/overview/dataQualityOverviewLogic'

import { metricsLogic } from '../metricsLogic'
import { catalogMetricsLogic } from './catalogMetricsLogic'

const METRICS = [
    { id: 'metric-approved', name: 'active_accounts', display_name: '', status: 'approved', created_at: '2026-09-01' },
    { id: 'metric-proposed', name: 'trial_conversion', display_name: '', status: 'proposed', created_at: '2026-09-02' },
    { id: 'metric-unlisted', name: 'weekly_signups', display_name: '', status: 'approved', created_at: '2026-09-03' },
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
                '/api/projects/:team_id/data_quality_checks/health/': [
                    {
                        subject_type: 'metric',
                        subject_uuid: 'metric-unlisted',
                        health: 'failing',
                        checks_total: 3,
                        checks_failing: 1,
                    },
                ],
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
        expect(logic.values.visibleMetrics.map((metric) => metric.id)).toEqual([
            'metric-proposed',
            'metric-approved',
            'metric-unlisted',
        ])

        logic.actions.setChecksFilter('with')
        expect(logic.values.visibleMetrics.map((metric) => metric.id)).toEqual(['metric-approved', 'metric-unlisted'])

        logic.actions.setChecksFilter('without')
        expect(logic.values.visibleMetrics.map((metric) => metric.id)).toEqual(['metric-proposed'])
    })

    it('counts checks from the health rollup for metrics whose checks are not loaded', () => {
        expect(logic.values.checkCountsByMetricId['metric-unlisted']).toEqual({ total: 3, failing: 1 })
    })

    it('opens the metric detail page', () => {
        const metric = logic.values.visibleMetrics.find(({ id }) => id === 'metric-approved')!

        logic.actions.openMetric(metric)

        expect(router.values.location.pathname).toEqual(
            `/project/${MOCK_TEAM_ID}${urls.dataCatalogMetric('active_accounts')}`
        )
    })

    it('goes back to the first page when the search changes', () => {
        logic.actions.setPage(2)
        expect(logic.values.page).toBe(2)

        metricsLogic.actions.setFilters({ search: 'trial' })
        expect(logic.values.page).toBe(1)
    })
})
