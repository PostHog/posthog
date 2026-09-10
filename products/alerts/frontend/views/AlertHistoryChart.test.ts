import {
    ForecastConditionType,
    ForecastEngineType,
    ForecastTargetDirection,
    InsightThresholdType,
} from '~/queries/schema/schema-general'

import type { AlertType } from '../types'
import { getAlertHistoryPoints, getAlertHistoryThresholds } from './AlertHistoryChart'

describe('getAlertHistoryThresholds', () => {
    const makeAlert = (overrides: Partial<AlertType>): AlertType =>
        ({
            threshold: { configuration: { type: InsightThresholdType.ABSOLUTE, bounds: { upper: 50 } } },
            ...overrides,
        }) as unknown as AlertType

    // A target alert converted from threshold mode keeps bounds the evaluation never reads, so the
    // chart has to draw the target instead.
    it.each([
        [ForecastTargetDirection.AT_LEAST, 'lower'],
        [ForecastTargetDirection.AT_MOST, 'upper'],
    ])('draws the target instead of the stored bounds for %s', (direction, expectedSide) => {
        const thresholds = getAlertHistoryThresholds(
            makeAlert({
                forecast_config: {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition: ForecastConditionType.TARGET_BY_DATE,
                    target: 100,
                    target_direction: direction,
                    target_date: '2026-12-01',
                },
            }),
            false
        )

        expect(thresholds).toEqual([{ direction: expectedSide, value: 100, label: 'Target (100)' }])
    })

    it('keeps the threshold bounds for a predicted breach forecast, which evaluates against them', () => {
        const thresholds = getAlertHistoryThresholds(
            makeAlert({
                forecast_config: {
                    type: 'ForecastConfig',
                    engine: ForecastEngineType.PROPHET,
                    condition: ForecastConditionType.FUTURE_BREACH,
                    horizon: 7,
                },
            }),
            false
        )

        expect(thresholds).toEqual([{ direction: 'upper', value: 50, label: 'Upper (50)' }])
    })

    it('keeps the threshold bounds for a plain threshold alert', () => {
        expect(getAlertHistoryThresholds(makeAlert({}), false)).toEqual([
            { direction: 'upper', value: 50, label: 'Upper (50)' },
        ])
    })
})

describe('getAlertHistoryPoints', () => {
    it('does not compare stored target forecasts with a target date configured later', () => {
        const alert = {
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target: 100,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date: '2026-12-01',
            },
        } as AlertType
        const points = [{ label: 'Sep 1', value: 90, firedAtTime: false }]

        expect(getAlertHistoryPoints(alert, points)).toEqual([
            { ...points[0], wouldFireUnderCurrentConfiguration: null },
        ])
    })
})
