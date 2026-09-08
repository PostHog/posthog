import {
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import { findFirstCrossing, forecastGoalLines, targetSummary } from './forecastPreviewUtils'

describe('findFirstCrossing', () => {
    it.each([
        ['upper-only crossing', [1, 2, 6, 3], { upper: 5 }, 2],
        ['lower-only crossing', [4, 3, -1, 2], { lower: 0 }, 2],
        ['both bounds set, crosses upper first', [1, 6, -5, 2], { lower: 0, upper: 5 }, 1],
        ['no crossing', [1, 2, 3, 4], { lower: 0, upper: 5 }, null],
        ['crossing at index 0', [6, 1, 2, 3], { upper: 5 }, 0],
        ['empty forecast', [], { upper: 5 }, null],
    ] as const)('%s', (_name, values, bounds, expected) => {
        expect(findFirstCrossing([...values], bounds)).toBe(expected)
    })
})

describe('targetSummary', () => {
    const projection = {
        predicted: 90,
        target: 100,
        target_date: '2026-12-01',
        evaluated_date: '2026-12-01',
        misses_target: true,
    }

    it('describes a missed minimum target', () => {
        expect(targetSummary(projection, ForecastTargetDirection.AT_LEAST)).toBe('Projected to finish below the target')
    })

    it('describes a missed maximum target', () => {
        expect(targetSummary(projection, ForecastTargetDirection.AT_MOST)).toBe('Projected to finish above the target')
    })

    it('describes an on-track target', () => {
        expect(targetSummary({ ...projection, misses_target: false }, ForecastTargetDirection.AT_LEAST)).toBe(
            'On track to reach the target'
        )
    })
})

describe('forecastGoalLines', () => {
    const breachConfig: ForecastConfig = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.FUTURE_BREACH,
        horizon: 7,
    }
    const targetConfig: ForecastConfig = {
        type: 'ForecastConfig',
        engine: ForecastEngineType.PROPHET,
        condition: ForecastConditionType.TARGET_BY_DATE,
        target: 1000,
        target_direction: ForecastTargetDirection.AT_LEAST,
        target_date: '2026-12-01',
    }

    it('carries both threshold bounds, so the axis can stretch to reach an off-scale one', () => {
        expect(forecastGoalLines({ lower: 10, upper: 9000 }, breachConfig)).toEqual([
            { value: 9000, label: 'More than 9,000', labelPosition: 'start', color: 'var(--danger)' },
            { value: 10, label: 'Less than 10', labelPosition: 'start', color: 'var(--danger)' },
        ])
    })

    it('carries the target of a target-by-date alert', () => {
        expect(forecastGoalLines(null, targetConfig)).toEqual([
            { value: 1000, label: 'Target 1,000', labelPosition: 'start' },
        ])
    })

    it('has no lines when a breach alert has no bounds yet', () => {
        expect(forecastGoalLines(null, breachConfig)).toEqual([])
    })
})
