import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { insightAlertsLogic, AnomalyPoint } from './insightAlertsLogic'
import { AlertType, AlertCheck } from './types'

const createMockAlert = (overrides: Partial<AlertType> = {}): AlertType =>
    ({
        id: 'alert-1',
        name: 'Test Alert',
        enabled: true,
        condition: { type: 'absolute_value' },
        threshold: {
            configuration: {
                type: 'absolute',
                bounds: { upper: 100, lower: 0 },
            },
        },
        config: { series_index: 0 },
        checks: [],
        ...overrides,
    }) as AlertType

const createMockCheck = (overrides: Partial<AlertCheck> = {}): AlertCheck =>
    ({
        id: 'check-1',
        state: 'firing',
        created_at: '2024-01-01T00:00:00Z',
        triggered_points: [],
        anomaly_scores: [],
        triggered_dates: [],
        interval: 'day',
        ...overrides,
    }) as AlertCheck

describe('insightAlertsLogic', () => {
    let logic: ReturnType<typeof insightAlertsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/alerts': {
                    results: [],
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('anomalyPoints selector', () => {
        it('returns empty array when no alerts', async () => {
            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            expect(logic.values.anomalyPoints).toEqual([])
        })

        it('returns empty array when alerts have no checks', async () => {
            const alertWithoutChecks = createMockAlert({ checks: [] })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alertWithoutChecks],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            expect(logic.values.anomalyPoints).toEqual([])
        })

        it('returns anomaly points from the most recent check', async () => {
            const check = createMockCheck({
                triggered_points: [5, 10],
                anomaly_scores: [3.5, 4.2],
                triggered_dates: ['2024-01-05', '2024-01-10'],
                interval: 'day',
            })
            const alert = createMockAlert({
                id: 'alert-1',
                name: 'Test Alert',
                checks: [check],
                config: { series_index: 0 },
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alert],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            const expectedPoints: AnomalyPoint[] = [
                {
                    index: 5,
                    date: '2024-01-05',
                    score: 3.5,
                    alertId: 'alert-1',
                    alertName: 'Test Alert',
                    seriesIndex: 0,
                },
                {
                    index: 10,
                    date: '2024-01-10',
                    score: 4.2,
                    alertId: 'alert-1',
                    alertName: 'Test Alert',
                    seriesIndex: 0,
                },
            ]
            expect(logic.values.anomalyPoints).toEqual(expectedPoints)
        })

        it('uses only the most recent check, ignoring older checks with anomalies', async () => {
            const recentCheckWithNoAnomalies = createMockCheck({
                id: 'check-recent',
                triggered_points: [],
                anomaly_scores: [],
                triggered_dates: [],
            })
            const olderCheckWithAnomalies = createMockCheck({
                id: 'check-old',
                triggered_points: [5],
                anomaly_scores: [3.5],
                triggered_dates: ['2024-01-05'],
            })
            const alert = createMockAlert({
                checks: [recentCheckWithNoAnomalies, olderCheckWithAnomalies],
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alert],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            // Should be empty because the most recent check has no anomalies
            expect(logic.values.anomalyPoints).toEqual([])
        })

        it('handles single score for all triggered points', async () => {
            const check = createMockCheck({
                triggered_points: [5, 10, 15],
                anomaly_scores: [3.5], // Single score for all points
                triggered_dates: ['2024-01-05', '2024-01-10', '2024-01-15'],
            })
            const alert = createMockAlert({ checks: [check] })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alert],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            // All points should have the same score
            expect(logic.values.anomalyPoints).toHaveLength(3)
            expect(logic.values.anomalyPoints.every((p) => p.score === 3.5)).toBe(true)
        })

        it('handles scores array matching triggered_points length', async () => {
            const check = createMockCheck({
                triggered_points: [5, 10],
                anomaly_scores: [3.5, 4.2], // Same length as triggered_points
                triggered_dates: ['2024-01-05', '2024-01-10'],
            })
            const alert = createMockAlert({ checks: [check] })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alert],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            expect(logic.values.anomalyPoints[0].score).toBe(3.5)
            expect(logic.values.anomalyPoints[1].score).toBe(4.2)
        })

        it('includes alerts when interval matches or is not set', async () => {
            // When check.interval is null/undefined, it should still show anomalies
            const check = createMockCheck({
                triggered_points: [5],
                anomaly_scores: [3.5],
                triggered_dates: ['2024-01-05'],
                interval: null, // No interval set - should still show
            })
            const alert = createMockAlert({ checks: [check] })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alert],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            // Should include the anomaly when interval is not set
            expect(logic.values.anomalyPoints).toHaveLength(1)
            expect(logic.values.anomalyPoints[0].index).toBe(5)
        })
    })

    describe('alertThresholdLines selector', () => {
        it('returns empty array when showAlertThresholdLines is false', async () => {
            const alert = createMockAlert({
                threshold: {
                    configuration: {
                        type: 'absolute',
                        bounds: { upper: 100, lower: 0 },
                    },
                },
            })

            useMocks({
                get: {
                    '/api/environments/:team_id/alerts': {
                        results: [alert],
                    },
                },
            })

            logic = insightAlertsLogic({
                insightId: 1,
                insightLogicProps: { dashboardItemId: 'new' },
            })
            logic.mount()

            await expectLogic(logic).toFinishListeners()

            // showAlertThresholdLines defaults to false
            expect(logic.values.alertThresholdLines).toEqual([])
        })
    })
})
