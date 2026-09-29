import api from 'lib/api'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { loadAppMetricsTimeSeries } from './appMetricsLogic'

describe('app metrics logic', () => {
    afterEach(() => {
        jest.restoreAllMocks()
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
})
