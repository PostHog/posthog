import { ForecastConditionType, ForecastEngineType, ForecastTargetDirection } from '~/queries/schema/schema-general'

import type { AlertFormType } from '../logic/alertFormLogic'
import { buildAlertSummary } from './alertSummary'

describe('buildAlertSummary', () => {
    const targetAlert = (target: number): AlertFormType =>
        ({
            forecast_config: {
                type: 'ForecastConfig',
                engine: ForecastEngineType.PROPHET,
                condition: ForecastConditionType.TARGET_BY_DATE,
                target,
                target_direction: ForecastTargetDirection.AT_LEAST,
                target_date: '2026-06-02',
            },
        }) as AlertFormType

    it.each([
        ['names the target once it is a number', 1500, 'the point forecast is below 1,500 on Jun 2, 2026'],
        ['stays generic while the target is empty', Number.NaN, 'the point forecast is below a target on Jun 2, 2026'],
    ])('%s', (_name, target, expected) => {
        expect(buildAlertSummary(targetAlert(target), 0).fires).toEqual(expected)
    })
})
