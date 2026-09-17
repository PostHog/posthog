import { InsightType, QueryBasedInsightModel } from '~/types'

import {
    DashboardRefreshJourneyController,
    getDashboardJourneyInsightType,
    isDashboardJourneyResultCommitted,
} from './dashboardRefreshJourney'

const startCustomerJourney = jest.fn()

jest.mock('lib/customerJourneys/startCustomerJourney', () => ({
    startCustomerJourney: (...args: unknown[]) => startCustomerJourney(...args),
}))

interface MockJourney {
    attemptId: string
    firstUseful: jest.Mock
    finish: jest.Mock
    dispose: jest.Mock
}

const handle = (): MockJourney => ({
    attemptId: 'attempt-1',
    firstUseful: jest.fn(),
    finish: jest.fn(),
    dispose: jest.fn(),
})

describe('DashboardRefreshJourneyController', () => {
    beforeEach(() => startCustomerJourney.mockReset())

    it('requires only visible supported insights whose saved short ID is unique in the full dashboard manifest', () => {
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()

        controller.setTileVisibility({ tileId: 13, insightShortId: 'unsupported', insightType: null }, true)
        controller.setTileVisibility({ tileId: 11, insightShortId: 'same', insightType: 'TRENDS' }, true)
        expect(
            controller.start(99, 'duplicated-only', [
                { tileId: 11, insightShortId: 'same' },
                { tileId: 12, insightShortId: 'same' },
                { tileId: 13, insightShortId: 'unsupported' },
            ])
        ).toBeNull()
        expect(startCustomerJourney).not.toHaveBeenCalled()

        controller.setTileVisibility({ tileId: 10, insightShortId: 'unique', insightType: 'RETENTION' }, true)

        expect(
            controller.start(99, 'refresh-id', [
                { tileId: 10, insightShortId: 'unique' },
                { tileId: 11, insightShortId: 'same' },
                { tileId: 12, insightShortId: 'same' },
                { tileId: 13, insightShortId: 'unsupported' },
            ])
        ).toMatchObject({
            attemptId: 'attempt-1',
            requiredTiles: {
                10: { insightShortId: 'unique', insightType: 'RETENTION' },
            },
        })
        expect(startCustomerJourney).toHaveBeenCalledWith({
            journey_name: 'dashboard_refresh',
            resource_type: 'dashboard',
            resource_id: 99,
            trigger: 'manual_refresh',
            readiness_contract_version: 1,
            readiness_scope: 'visible_product_analytics_tiles',
            attempt_id: 'refresh-id',
        })

        const result: unknown[] = []
        expect(controller.dataReady('attempt-1', 10, result)?.expectedResult).toBe(result)
        expect(controller.dataReady('attempt-1', 11, [{ count: 1 }])).toBeNull()

        controller.renderCommitted('attempt-1', 10)

        expect(journey.firstUseful).toHaveBeenCalledTimes(1)
        expect(journey.finish).toHaveBeenCalledWith('usable', {
            total_count: 1,
            ready_count: 1,
            failed_count: 0,
            pending_count: 0,
            excluded_count: 2,
            tile_results_truncated: false,
            tile_results: [
                {
                    tile_id: 10,
                    insight_short_id: 'unique',
                    insight_type: 'RETENTION',
                    state: 'ready',
                    duration_ms: expect.any(Number),
                },
            ],
            insight_type_summary: {
                RETENTION: {
                    total_count: 1,
                    ready_count: 1,
                    failed_count: 0,
                    max_duration_ms: expect.any(Number),
                },
            },
        })
    })

    it('retains differently timed committed tiles as identified rows', () => {
        let time = 100
        const nowSpy = jest.spyOn(performance, 'now').mockImplementation(() => time)
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()
        controller.setTileVisibility({ tileId: 20, insightShortId: 'retention', insightType: 'RETENTION' }, true)
        controller.setTileVisibility({ tileId: 10, insightShortId: 'trends', insightType: 'TRENDS' }, true)

        try {
            controller.start(99, 'refresh-id', [
                { tileId: 20, insightShortId: 'retention' },
                { tileId: 10, insightShortId: 'trends' },
            ])
            time = 130
            controller.renderCommitted('attempt-1', 20)
            time = 165
            controller.renderCommitted('attempt-1', 10)

            expect(journey.finish).toHaveBeenCalledWith(
                'usable',
                expect.objectContaining({
                    total_count: 2,
                    ready_count: 2,
                    tile_results_truncated: false,
                    tile_results: [
                        {
                            tile_id: 10,
                            insight_short_id: 'trends',
                            insight_type: 'TRENDS',
                            state: 'ready',
                            duration_ms: 65,
                        },
                        {
                            tile_id: 20,
                            insight_short_id: 'retention',
                            insight_type: 'RETENTION',
                            state: 'ready',
                            duration_ms: 30,
                        },
                    ],
                })
            )
        } finally {
            nowSpy.mockRestore()
        }
    })

    it('caps tile rows by numeric ID rather than completion order while retaining the full denominator', () => {
        let time = 100
        const nowSpy = jest.spyOn(performance, 'now').mockImplementation(() => time)
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()
        const manifest = Array.from({ length: 52 }, (_, index) => {
            const tileId = 52 - index
            const insightShortId = `insight-${tileId}`
            controller.setTileVisibility({ tileId, insightShortId, insightType: 'TRENDS' }, true)
            return { tileId, insightShortId }
        })

        try {
            controller.start(99, 'refresh-id', manifest)
            time = 110
            controller.renderCommitted('attempt-1', 52)
            time = 125
            controller.renderCommitted('attempt-1', 1)
            time = 140
            controller.renderCommitted('attempt-1', 50)
            controller.dispose('cancelled')

            expect(journey.finish).toHaveBeenCalledWith(
                'cancelled',
                expect.objectContaining({
                    total_count: 52,
                    ready_count: 3,
                    pending_count: 49,
                    tile_results_truncated: true,
                    tile_results: expect.any(Array),
                })
            )
            const summary = journey.finish.mock.calls[0][1]
            expect(summary.tile_results).toHaveLength(50)
            expect(summary.tile_results.map((row: { tile_id: number }) => row.tile_id)).toEqual(
                Array.from({ length: 50 }, (_, index) => index + 1)
            )
            expect(summary.tile_results).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ tile_id: 1, state: 'ready', duration_ms: 25 }),
                    expect.objectContaining({ tile_id: 50, state: 'ready', duration_ms: 40 }),
                ])
            )
            expect(summary.tile_results).not.toEqual(expect.arrayContaining([expect.objectContaining({ tile_id: 52 })]))
        } finally {
            nowSpy.mockRestore()
        }
    })

    it('ignores stale generations and disposes explicit terminal reasons', () => {
        const first = handle()
        const second = { ...handle(), attemptId: 'attempt-2' }
        const third = { ...handle(), attemptId: 'attempt-3' }
        startCustomerJourney.mockReturnValueOnce(first).mockReturnValueOnce(second).mockReturnValueOnce(third)
        const controller = new DashboardRefreshJourneyController()
        controller.setTileVisibility({ tileId: 1, insightShortId: 'one', insightType: 'RETENTION' }, true)

        const manifest = [{ tileId: 1, insightShortId: 'one' }]
        controller.start(99, 'refresh-a', manifest)
        controller.start(99, 'refresh-b', manifest)
        expect(first.finish).toHaveBeenCalledWith(
            'superseded',
            expect.objectContaining({ total_count: 1, ready_count: 0, pending_count: 1, end_reason: 'superseded' })
        )
        expect(controller.dataReady('attempt-1', 1, [])).toBeNull()
        expect(controller.renderCommitted('attempt-1', 1)).toBe(false)

        controller.dispose('cancelled')
        expect(second.finish).toHaveBeenCalledWith(
            'cancelled',
            expect.objectContaining({ total_count: 1, ready_count: 0, pending_count: 1, end_reason: 'cancelled' })
        )

        controller.start(99, 'refresh-c', manifest)
        controller.dispose('observation_stopped')
        expect(third.finish).toHaveBeenCalledWith(
            'observation_stopped',
            expect.objectContaining({
                total_count: 1,
                ready_count: 0,
                pending_count: 1,
                end_reason: 'observation_stopped',
            })
        )
    })

    it('finishes failed without shrinking the fixed denominator', () => {
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()
        controller.setTileVisibility({ tileId: 1, insightShortId: 'one', insightType: 'FUNNELS' }, true)
        controller.setTileVisibility({ tileId: 2, insightShortId: 'two', insightType: 'RETENTION' }, true)
        controller.setTileVisibility({ tileId: 3, insightShortId: 'three', insightType: 'PATHS' }, true)
        controller.start(99, 'refresh-id', [
            { tileId: 1, insightShortId: 'one' },
            { tileId: 2, insightShortId: 'two' },
            { tileId: 3, insightShortId: 'three' },
        ])
        controller.setTileVisibility({ tileId: 2, insightShortId: 'two', insightType: 'RETENTION' }, false)

        controller.renderCommitted('attempt-1', 2)
        controller.failed('attempt-1', 1, 'query_error')

        expect(journey.finish).toHaveBeenCalledWith(
            'failed',
            expect.objectContaining({
                total_count: 3,
                ready_count: 1,
                failed_count: 1,
                pending_count: 1,
                error_type: 'query_error',
                tile_results_truncated: false,
                tile_results: [
                    {
                        tile_id: 1,
                        insight_short_id: 'one',
                        insight_type: 'FUNNELS',
                        state: 'failed',
                    },
                    {
                        tile_id: 2,
                        insight_short_id: 'two',
                        insight_type: 'RETENTION',
                        state: 'ready',
                        duration_ms: expect.any(Number),
                    },
                    {
                        tile_id: 3,
                        insight_short_id: 'three',
                        insight_type: 'PATHS',
                        state: 'pending',
                    },
                ],
            })
        )
    })
})

describe('dashboard refresh readiness helpers', () => {
    it('supports the six product analytics query types, including retention, and rejects other nodes', () => {
        const insight = (kind: string): QueryBasedInsightModel =>
            ({ query: { kind: 'InsightVizNode', source: { kind } } }) as unknown as QueryBasedInsightModel

        expect(getDashboardJourneyInsightType(insight('TrendsQuery'))).toBe('TRENDS')
        expect(getDashboardJourneyInsightType(insight('StickinessQuery'))).toBe('STICKINESS')
        expect(getDashboardJourneyInsightType(insight('LifecycleQuery'))).toBe('LIFECYCLE')
        expect(getDashboardJourneyInsightType(insight('FunnelsQuery'))).toBe('FUNNELS')
        expect(getDashboardJourneyInsightType(insight('RetentionQuery'))).toBe('RETENTION')
        expect(getDashboardJourneyInsightType(insight('PathsQuery'))).toBe('PATHS')
        expect(getDashboardJourneyInsightType(insight('PathsV2Query'))).toBeNull()
        expect(
            getDashboardJourneyInsightType({ query: { kind: 'DataTableNode' } } as QueryBasedInsightModel)
        ).toBeNull()
    })

    it('requires the committed visualization result to be the exact response reference, including empty retention', () => {
        const emptyRetention: unknown[] = []
        expect(isDashboardJourneyResultCommitted(emptyRetention, emptyRetention)).toBe(true)
        expect(isDashboardJourneyResultCommitted([], emptyRetention)).toBe(false)
        expect(isDashboardJourneyResultCommitted(null, emptyRetention)).toBe(false)
        expect(InsightType.RETENTION).toBeTruthy()
    })
})
