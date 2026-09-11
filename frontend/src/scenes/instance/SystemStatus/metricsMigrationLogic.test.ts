import api from 'lib/api'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { metricsMigrationLogic } from './metricsMigrationLogic'

jest.mock('lib/api')

const REPORT = {
    generated_at: '2026-09-11T00:00:00+00:00',
    summary: {
        grafana_metric_names: 2,
        posthog_ingested_names: 1,
        covered: 1,
        uncovered: 1,
        coverage_pct: 50.0,
        dashboards_total: 1,
        dashboards_fully_covered: 0,
    },
    dashboards: [
        {
            title: 'dash a',
            file: 'a.json',
            metric_count: 2,
            covered_metrics: 1,
            uncovered_metrics: 1,
            coverage_pct: 50.0,
            status: 'partial',
        },
    ],
    uncovered: [{ name: 'missing_one', dashboards: ['dash a'] }],
}

describe('metricsMigrationLogic', () => {
    beforeEach(() => {
        initKeaTests()
        metricsMigrationLogic.mount()
        jest.mocked(api.get).mockResolvedValue({ results: REPORT } as any)
    })

    afterEach(() => {
        metricsMigrationLogic.unmount()
        jest.clearAllMocks()
    })

    it('loads the snapshot report by default', async () => {
        await expectLogic(metricsMigrationLogic, () => {
            metricsMigrationLogic.actions.loadReport()
        })
            .toDispatchActions(['loadReport', 'loadReportSuccess'])
            .toMatchValues({ report: REPORT })

        expect(jest.mocked(api.get)).toHaveBeenCalledWith('api/instance_status/metrics_migration')
    })

    it('requests live recompute when live is enabled', async () => {
        await expectLogic(metricsMigrationLogic, () => {
            metricsMigrationLogic.actions.setLive(true)
            metricsMigrationLogic.actions.loadReport()
        })
            .toDispatchActions(['setLive', 'loadReport', 'loadReportSuccess'])
            .toMatchValues({ live: true, report: REPORT })

        expect(jest.mocked(api.get)).toHaveBeenCalledWith('api/instance_status/metrics_migration?live=true')
    })
})
