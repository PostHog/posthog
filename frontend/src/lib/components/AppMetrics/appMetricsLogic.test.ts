import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { useMocks } from '~/mocks/jest'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { appMetricsLogic, loadAppMetricsTimeSeries } from './appMetricsLogic'

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

    it.each([
        {
            name: 'loads once a concurrency 429 clears',
            refusals: 1,
            outcome: { series: [{ name: 'rows_synced', values: [7] }] },
        },
        { name: 'fails when the retry gets a 429 too', refusals: 2, outcome: { status: 429 } },
    ])('time series $name', async ({ refusals, outcome }) => {
        initKeaTests()
        let refusalsLeft = refusals
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind/': () =>
                    refusalsLeft-- > 0
                        ? new Response(JSON.stringify({ detail: 'Too many queries.' }), {
                              status: 429,
                              headers: { 'Content-Type': 'application/json', 'Retry-After': '5' },
                          })
                        : [200, { results: [[['2026-10-01'], 'rows_synced', [7]]] }],
            },
        })
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate', 'queueMicrotask'] })
        try {
            let settled: Record<string, unknown> | undefined
            void loadAppMetricsTimeSeries(
                {
                    appSource: 'warehouse_source_sync',
                    breakdownBy: 'metric_name',
                    dateFrom: '2026-10-01T00:00:00Z',
                    dateTo: '2026-10-02T00:00:00Z',
                },
                'UTC'
            ).then(
                (result) => (settled = { series: result.series }),
                (error) => (settled = { status: error.status })
            )
            let waitedMs = 0
            while (!settled && waitedMs < 10_000) {
                await jest.advanceTimersByTimeAsync(500)
                waitedMs += 500
            }

            expect(settled).toEqual(outcome)
            expect(waitedMs).toBeGreaterThanOrEqual(5_000)
        } finally {
            jest.useRealTimers()
        }
    })

    it.each(['loadAppMetricsTrends', 'loadAppMetricsTrendsPreviousPeriod'] as const)(
        '%s ignores an older load that fails after a newer one finished',
        async (load) => {
            initKeaTests()
            let failFirstLoad = (): void => {}
            jest.spyOn(api, 'queryHogQL')
                .mockImplementationOnce(
                    () => new Promise((_, reject) => (failFirstLoad = () => reject(new ApiError('Server error', 500))))
                )
                .mockResolvedValue({ results: [[['2026-10-01'], 'success', [3]]] } as HogQLQueryResponse)
            const logic = appMetricsLogic({ logicKey: 'superseded', forceParams: { appSource: 'hog_function' } })
            logic.mount()

            logic.actions[load]()
            await waitFor(() => expect(api.queryHogQL).toHaveBeenCalledTimes(1))
            await expectLogic(logic, () => logic.actions[load]()).toDispatchActions([`${load}Success`])
            failFirstLoad()
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toNotHaveDispatchedActions([`${load}Failure`])
            logic.unmount()
        }
    )
})
