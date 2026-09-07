import { ForecastTargetDirection } from '~/queries/schema/schema-general'

import { findFirstCrossing, targetSummary } from './forecastPreviewUtils'

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
