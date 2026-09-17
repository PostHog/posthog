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
        controller.start(99, 'refresh-id', [
            { tileId: 1, insightShortId: 'one' },
            { tileId: 2, insightShortId: 'two' },
        ])
        controller.setTileVisibility({ tileId: 2, insightShortId: 'two', insightType: 'RETENTION' }, false)

        controller.failed('attempt-1', 1, 'query_error')

        expect(journey.finish).toHaveBeenCalledWith(
            'failed',
            expect.objectContaining({
                total_count: 2,
                ready_count: 0,
                failed_count: 1,
                pending_count: 1,
                error_type: 'query_error',
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
