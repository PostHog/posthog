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

    it('pages the proposed list and the approved list apart', () => {
        const approved = Array.from({ length: 7 }, (_, index) => ({
            ...METRICS[0],
            id: `metric-approved-${index}`,
            name: `approved_${index}`,
        }))
        metricsLogic.actions.loadMetricsSuccess([METRICS[1], ...approved] as any)

        logic.actions.setPage('approved', 2)

        const { proposed, approved: approvedPage, all } = logic.values.listPages
        expect(proposed.metrics.map((metric) => metric.id)).toEqual(['metric-proposed'])
        expect(proposed.currentPage).toBe(1)
        expect(approvedPage.metrics.map((metric) => metric.id)).toEqual(['metric-approved-5', 'metric-approved-6'])
        expect(approvedPage.pageCount).toBe(2)
        expect(all.currentPage).toBe(1)
    })

    it('goes back to the first page of each list when the search changes', () => {
        logic.actions.setPage('all', 2)
        logic.actions.setPage('approved', 3)
        expect(logic.values.pages).toEqual({ all: 2, proposed: 1, approved: 3 })

        metricsLogic.actions.setFilters({ search: 'trial' })
        expect(logic.values.pages).toEqual({ all: 1, proposed: 1, approved: 1 })
    })
})
