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

    it('keeps automatic whole-dashboard refreshes in a distinct trigger cohort', () => {
        startCustomerJourney.mockReturnValue(handle())
        const controller = new DashboardRefreshJourneyController()
        controller.setTileVisibility({ tileId: 1, insightShortId: 'one', insightType: 'TRENDS' }, true)

        controller.start(99, 'automatic-id', [{ tileId: 1, insightShortId: 'one' }], 'automatic_refresh')

        expect(startCustomerJourney).toHaveBeenCalledWith(
            expect.objectContaining({
                journey_name: 'dashboard_refresh',
                trigger: 'automatic_refresh',
                attempt_id: 'automatic-id',
            })
        )
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

    it('freezes the initial visible set only after the complete manifest has a real observation for every insight', () => {
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()
        const manifest = [
            { tileId: 1, insightShortId: 'unique' },
            { tileId: 2, insightShortId: 'duplicate' },
            { tileId: 3, insightShortId: 'duplicate' },
            { tileId: 4, insightShortId: 'unsupported' },
            { tileId: 5, insightShortId: 'offscreen' },
        ]

        controller.beginInitialLoad(99, 'attempt-1')
        expect(controller.planInitialLoad('attempt-1', manifest, [], { 1: [] })).toBeNull()
        expect(
            controller.setTileVisibility({ tileId: 1, insightShortId: 'unique', insightType: 'RETENTION' }, true)
        ).toBeNull()
        controller.setTileVisibility({ tileId: 2, insightShortId: 'duplicate', insightType: 'TRENDS' }, true)
        controller.setTileVisibility({ tileId: 3, insightShortId: 'duplicate', insightType: 'TRENDS' }, true)
        controller.setTileVisibility({ tileId: 4, insightShortId: 'unsupported', insightType: null }, true)

        const activation = controller.setTileVisibility(
            { tileId: 5, insightShortId: 'offscreen', insightType: 'PATHS' },
            false
        )

        expect(activation).toMatchObject({
            attemptId: 'attempt-1',
            requiredTiles: {
                1: { insightShortId: 'unique', insightType: 'RETENTION' },
            },
        })
        expect(activation?.renderReadiness).toEqual([
            expect.objectContaining({ tileId: 1, expectedResult: expect.any(Array) }),
        ])
        expect(startCustomerJourney).toHaveBeenCalledWith({
            journey_name: 'dashboard_open',
            resource_type: 'dashboard',
            resource_id: 99,
            trigger: 'initial_load',
            readiness_contract_version: 1,
            readiness_scope: 'visible_product_analytics_tiles',
            attempt_id: 'attempt-1',
        })

        expect(
            controller.setTileVisibility({ tileId: 5, insightShortId: 'offscreen', insightType: 'PATHS' }, true)
        ).toBeNull()
        expect(controller.dataReady('attempt-1', 5, [{ count: 5 }])).toBeNull()
    })

    it('selects fresh cached and stale replacement references across the initial viewport gate', () => {
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()
        const freshEmpty: unknown[] = []
        const staleCached = [{ count: 1 }]
        const replacement = [{ count: 2 }]

        controller.beginInitialLoad(99, 'attempt-1')
        controller.setTileVisibility({ tileId: 1, insightShortId: 'fresh', insightType: 'RETENTION' }, true)
        controller.planInitialLoad(
            'attempt-1',
            [
                { tileId: 1, insightShortId: 'fresh' },
                { tileId: 2, insightShortId: 'stale' },
            ],
            [2],
            { 1: freshEmpty, 2: staleCached }
        )

        expect(controller.dataReady('attempt-1', 2, replacement)).toBeNull()
        const activation = controller.setTileVisibility(
            { tileId: 2, insightShortId: 'stale', insightType: 'TRENDS' },
            true
        )

        expect(activation?.renderReadiness).toEqual([
            expect.objectContaining({ tileId: 1, expectedResult: freshEmpty }),
            expect.objectContaining({ tileId: 2, expectedResult: replacement }),
        ])
        expect(activation?.renderReadiness).not.toEqual(
            expect.arrayContaining([expect.objectContaining({ tileId: 2, expectedResult: staleCached })])
        )

        controller.renderCommitted('attempt-1', 1)
        expect(journey.finish).not.toHaveBeenCalled()
        controller.renderCommitted('attempt-1', 2)
        expect(journey.finish).toHaveBeenCalledWith(
            'usable',
            expect.objectContaining({ total_count: 2, ready_count: 2 })
        )
    })

    it('reports an observed initial dashboard with no supported visible tiles as observation stopped', () => {
        const journey = handle()
        startCustomerJourney.mockReturnValue(journey)
        const controller = new DashboardRefreshJourneyController()

        controller.beginInitialLoad(99, 'attempt-1')
        controller.planInitialLoad(
            'attempt-1',
            [
                { tileId: 1, insightShortId: 'unsupported' },
                { tileId: 2, insightShortId: 'offscreen' },
            ],
            [],
            {}
        )
        controller.setTileVisibility({ tileId: 1, insightShortId: 'unsupported', insightType: null }, true)
        expect(
            controller.setTileVisibility({ tileId: 2, insightShortId: 'offscreen', insightType: 'PATHS' }, false)
        ).toBeNull()

        expect(journey.finish).toHaveBeenCalledWith('observation_stopped', {
            total_count: 0,
            ready_count: 0,
            failed_count: 0,
            pending_count: 0,
            excluded_count: 1,
            insight_type_summary: {},
            tile_results: [],
            tile_results_truncated: false,
            end_reason: 'observation_stopped',
        })
    })

    it('finishes initial load failures without a fabricated denominator before sealing and preserves it after sealing', () => {
        const beforeSeal = handle()
        const afterSeal = { ...handle(), attemptId: 'attempt-2' }
        startCustomerJourney.mockReturnValueOnce(beforeSeal).mockReturnValueOnce(afterSeal)
        const controller = new DashboardRefreshJourneyController()

        controller.beginInitialLoad(99, 'attempt-1')
        controller.failLoad('attempt-1', 'load_error')
        expect(beforeSeal.finish).toHaveBeenCalledWith('failed', { error_type: 'load_error' })

        controller.beginInitialLoad(99, 'attempt-2')
        controller.setTileVisibility({ tileId: 1, insightShortId: 'one', insightType: 'FUNNELS' }, true)
        controller.planInitialLoad('attempt-2', [{ tileId: 1, insightShortId: 'one' }], [1], {})
        controller.failLoad('attempt-2', 'load_error')
        expect(afterSeal.finish).toHaveBeenCalledWith(
            'failed',
            expect.objectContaining({ total_count: 1, ready_count: 0, pending_count: 1, error_type: 'load_error' })
        )
    })

    it('reuses real observations from still-mounted cards for a replacement initial generation', () => {
        const first = handle()
        const second = { ...handle(), attemptId: 'attempt-2' }
        startCustomerJourney.mockReturnValueOnce(first).mockReturnValueOnce(second)
        const controller = new DashboardRefreshJourneyController()
        const manifest = [{ tileId: 1, insightShortId: 'one' }]

        controller.setTileVisibility({ tileId: 1, insightShortId: 'one', insightType: 'TRENDS' }, true)
        controller.beginInitialLoad(99, 'attempt-1')
        expect(controller.planInitialLoad('attempt-1', manifest, [], { 1: [] })).not.toBeNull()

        controller.beginInitialLoad(99, 'attempt-2')
        expect(controller.planInitialLoad('attempt-2', manifest, [], { 1: [] })).toMatchObject({
            attemptId: 'attempt-2',
            requiredTiles: { 1: { insightShortId: 'one', insightType: 'TRENDS' } },
        })
        expect(first.finish).toHaveBeenCalledWith(
            'superseded',
            expect.objectContaining({ total_count: 1, pending_count: 1, end_reason: 'superseded' })
        )
    })

    it('reports initial-load exit without invented counts before sealing and with the frozen partial summary after', () => {
        const beforeSeal = handle()
        const afterSeal = { ...handle(), attemptId: 'attempt-2' }
        startCustomerJourney.mockReturnValueOnce(beforeSeal).mockReturnValueOnce(afterSeal)
        const controller = new DashboardRefreshJourneyController()

        controller.beginInitialLoad(99, 'attempt-1')
        controller.dispose('observation_stopped')
        expect(beforeSeal.finish).toHaveBeenCalledWith('exited', { end_reason: 'exited' })

        controller.beginInitialLoad(99, 'attempt-2')
        controller.setTileVisibility({ tileId: 1, insightShortId: 'one', insightType: 'TRENDS' }, true)
        controller.setTileVisibility({ tileId: 2, insightShortId: 'two', insightType: 'PATHS' }, true)
        controller.planInitialLoad(
            'attempt-2',
            [
                { tileId: 1, insightShortId: 'one' },
                { tileId: 2, insightShortId: 'two' },
            ],
            [],
            { 1: [], 2: [] }
        )
        controller.renderCommitted('attempt-2', 1)
        controller.dispose('observation_stopped')

        expect(afterSeal.finish).toHaveBeenCalledWith(
            'exited',
            expect.objectContaining({
                total_count: 2,
                ready_count: 1,
                failed_count: 0,
                pending_count: 1,
                end_reason: 'exited',
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
