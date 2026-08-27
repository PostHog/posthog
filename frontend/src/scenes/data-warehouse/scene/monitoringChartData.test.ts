import type { ManagedWarehouseMonitoringSeriesResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { buildMonitoringChartData } from './monitoringChartData'

describe('buildMonitoringChartData', () => {
    it('normalizes independently fetched series to a shared time grid', () => {
        const response = (
            metric: string,
            timestamps: string[],
            values: number[]
        ): ManagedWarehouseMonitoringSeriesResponseApi => ({
            schema_version: 1,
            org_id: 'org-1',
            metric,
            unit: 'seconds',
            start: timestamps[0] ?? '',
            end: timestamps[timestamps.length - 1] ?? '',
            step_seconds: 60,
            series: [
                {
                    labels: {},
                    points: timestamps.map((timestamp, index) => ({ timestamp, value: values[index] })),
                },
            ],
        })

        const chartData = buildMonitoringChartData(
            [
                response('duration_p50', ['2026-08-12T10:00:01Z', '2026-08-12T10:01:01Z'], [1, 2]),
                response('duration_p95', ['2026-08-12T10:00:03Z', '2026-08-12T10:01:03Z'], [10, 20]),
            ],
            [
                { metric: 'duration_p50', fallbackLabel: 'p50' },
                { metric: 'duration_p95', fallbackLabel: 'p95' },
            ]
        )

        expect(chartData.labels).toEqual(['2026-08-12T10:00:00.000Z', '2026-08-12T10:01:00.000Z'])
        expect(chartData.series).toEqual([
            { key: 'duration_p50:[]', label: 'p50', data: [1, 2] },
            { key: 'duration_p95:[]', label: 'p95', data: [10, 20] },
        ])
    })

    it('preserves timestamps that are missing from one series', () => {
        const chartData = buildMonitoringChartData(
            [
                {
                    schema_version: 1,
                    org_id: 'org-1',
                    metric: 'query_rate',
                    unit: 'queries_per_second',
                    start: '2026-08-12T10:00:00Z',
                    end: '2026-08-12T10:02:00Z',
                    step_seconds: 60,
                    series: [
                        {
                            labels: { status: 'success' },
                            points: [
                                { timestamp: '2026-08-12T10:00:00Z', value: 10 },
                                { timestamp: '2026-08-12T10:01:00Z', value: 11 },
                                { timestamp: '2026-08-12T10:02:00Z', value: 12 },
                            ],
                        },
                        {
                            labels: { status: 'error' },
                            points: [{ timestamp: '2026-08-12T10:01:00Z', value: 1 }],
                        },
                    ],
                },
            ],
            [{ metric: 'query_rate', fallbackLabel: 'Queries' }]
        )

        expect(chartData.labels).toEqual([
            '2026-08-12T10:00:00.000Z',
            '2026-08-12T10:01:00.000Z',
            '2026-08-12T10:02:00.000Z',
        ])
        expect(chartData.series).toEqual([
            {
                key: 'query_rate:[["status","error"]]',
                label: 'Error',
                data: [Number.NaN, 1, Number.NaN],
            },
            {
                key: 'query_rate:[["status","success"]]',
                label: 'Success',
                data: [10, 11, 12],
            },
        ])
    })
})
