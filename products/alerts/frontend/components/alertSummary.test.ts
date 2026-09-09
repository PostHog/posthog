import { ForecastConditionType, ForecastEngineType, ForecastTargetDirection } from '~/queries/schema/schema-general'

import type { AlertFormType } from '../logic/alertFormLogic'
import { buildAlertSummary } from './alertSummary'

describe('buildAlertSummary', () => {
    const targetAlert = (target: number, target_date = '2026-06-02'): AlertFormType =>
        ({
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date,
            },
        }) as AlertFormType

    it.each([
        ['names the target once it is a number', 1500, 'the point forecast is below 1,500 on Jun 2, 2026'],
        ['stays generic while the target is empty', Number.NaN, 'the point forecast is below a target on Jun 2, 2026'],
    ])('%s', (_name, target, expected) => {
        expect(buildAlertSummary(targetAlert(target), 0).fires).toEqual(expected)
    })

    // The server fires an upcoming-breach alert on the latest completed value before it forecasts,
    // so a review step that named only the forecast would leave out a rule the alert runs.
    it('names both firing rules of an upcoming breach alert', () => {
        const breachAlert = {
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.FUTURE_BREACH,
                horizon: 7,
            },
        } as AlertFormType
        expect(buildAlertSummary(breachAlert, 0).fires).toEqual(
            'the latest value or the point forecast crosses your threshold'
        )
    })

    // The server accepts ISO week dates, which dayjs reads as an invalid date.
    it('shows a stored date it cannot read instead of the words Invalid Date', () => {
        expect(buildAlertSummary(targetAlert(1500, '2026-W40-1'), 0).fires).toEqual(
            'the point forecast is below 1,500 on 2026-W40-1'
        )
    })
})
