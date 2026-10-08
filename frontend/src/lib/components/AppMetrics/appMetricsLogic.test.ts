import api from 'lib/api'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { loadAppMetricsTimeSeries } from './appMetricsLogic'

describe('app metrics logic', () => {
    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('filters a time series to a set of instance ids', async () => {
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as HogQLQueryResponse)

        await loadAppMetricsTimeSeries(
            {
                appSource: 'warehouse_source_sync',
                instanceIds: ['schema-1', 'schema-2'],
                breakdownBy: 'metric_name',
                dateFrom: '2026-10-01T00:00:00Z',
                dateTo: '2026-10-02T00:00:00Z',
            },
            'UTC'
        )

        expect(jest.mocked(api.queryHogQL).mock.calls[0][0]).toContain("instance_id IN ['schema-1', 'schema-2']")
    })

    it('keeps ISO offsets that distinguish repeated local hours', async () => {
        const labels = ['2026-11-01T01:00:00-07:00', '2026-11-01T01:00:00-08:00']
        jest.spyOn(api, 'queryHogQL').mockResolvedValue({
            results: [[labels, 'success', [2, 3]]],
        } as HogQLQueryResponse)

        const result = await loadAppMetricsTimeSeries(
            {
                appSource: 'hog_flow',
                breakdownBy: 'metric_kind',
                interval: 'hour',
                dateFrom: '2026-11-01T00:00:00-07:00',
                dateTo: '2026-11-01T03:00:00-08:00',
            },
            'US/Pacific'
        )

        expect(result).toEqual({
            labels,
            interval: 'hour',
            timezone: 'US/Pacific',
            series: [{ name: 'success', values: [2, 3] }],
        })
    })

    it('groups into a constant breakdown when no breakdown is set', async () => {
        const querySpy = jest.spyOn(api, 'queryHogQL').mockResolvedValue({
            results: [[['2026-11-01T00:00:00Z'], '', [5]]],
        } as HogQLQueryResponse)

        const result = await loadAppMetricsTimeSeries(
            {
                appSource: 'data_warehouse',
                metricName: 'rows_synced',
                instanceId: 'destination-1',
                interval: 'day',
                dateFrom: '2026-11-01T00:00:00Z',
                dateTo: '2026-11-02T00:00:00Z',
            },
            'UTC'
        )

        const query = querySpy.mock.calls[0][0] as string
        expect(query).toContain("'' AS breakdown")
        expect(query).not.toContain('undefined')
        expect(result.series).toEqual([{ name: '', values: [5] }])
    })
})
