import {
    ForecastConditionType,
    ForecastConfig,
    ForecastEngineType,
    ForecastTargetDirection,
} from '~/queries/schema/schema-general'

import {
    bucketLabel,
    findFirstCrossing,
    findObservedBreach,
    forecastGoalLines,
    targetSummary,
} from './forecastPreviewUtils'

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

describe('findObservedBreach', () => {
    it.each([
        ['latest value past the upper bound', [1, 2, 9], { upper: 5 }, { index: 2, value: 9 }],
        ['latest value past the lower bound', [4, 3, -2], { lower: 0 }, { index: 2, value: -2 }],
        ['latest value inside both bounds', [1, 9, 3], { lower: 0, upper: 5 }, null],
        // The backend only tests the last value, so an old spike must not report a breach now.
        ['earlier point breached, latest value fine', [9, 9, 3], { upper: 5 }, null],
        ['no bounds set', [1, 2, 9], null, null],
        ['no history', [], { upper: 5 }, null],
    ] as const)('%s', (_name, data, bounds, expected) => {
        expect(findObservedBreach([...data], bounds)).toEqual(expected)
    })
})

describe('bucketLabel', () => {
    it.each([
        // An hourly insight puts up to 24 buckets on one day, so the hour identifies the bucket.
        ['hourly bucket keeps the hour', '2026-09-13T23:00:00', 'hour', 'Sep 13, 2026 23:00'],
        ['hourly bucket from a space-separated timestamp', '2026-09-13 07:00:00', 'hour', 'Sep 13, 2026 07:00'],
        ['daily bucket drops the time', '2026-09-13T00:00:00', 'day', 'Sep 13, 2026'],
        ['weekly bucket drops the time', '2026-09-13T00:00:00', 'week', 'Sep 13, 2026'],
        ['monthly bucket drops the time', '2026-09-01T00:00:00', 'month', 'Sep 1, 2026'],
        ['unknown interval falls back to the day', '2026-09-13T23:00:00', null, 'Sep 13, 2026'],
        ['an unparseable value is passed through', 'not a date', 'hour', 'not a date'],
    ] as const)('%s', (_name, value, interval, expected) => {
        expect(bucketLabel(value, interval)).toBe(expected)
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
