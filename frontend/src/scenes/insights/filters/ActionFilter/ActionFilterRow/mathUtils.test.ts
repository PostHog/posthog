import { PropertyMathType } from '~/types'

import { getDefaultPropertyMathType } from './mathUtils'

describe('getDefaultPropertyMathType', () => {
    test.each([
        ['defaults to median', undefined, undefined, false, PropertyMathType.Median],
        // median can't be rolled up across histogram buckets, so the default must stay backend-safe
        ['falls back to average for histogram breakdowns', undefined, undefined, true, PropertyMathType.Average],
        ['keeps the currently selected property math', PropertyMathType.P90, undefined, false, PropertyMathType.P90],
        [
            'uses the first allowed property math type',
            undefined,
            [PropertyMathType.Sum, PropertyMathType.Average],
            false,
            PropertyMathType.Sum,
        ],
        [
            'skips allowed types unsupported for histogram breakdowns',
            undefined,
            [PropertyMathType.Median, PropertyMathType.Sum],
            true,
            PropertyMathType.Sum,
        ],
        [
            'falls back to average when no allowed type supports histogram breakdowns',
            undefined,
            [PropertyMathType.Median, PropertyMathType.P90],
            true,
            PropertyMathType.Average,
        ],
    ])('%s', (_name, math, allowedMathTypes, isHistogramBreakdown, expected) => {
        expect(getDefaultPropertyMathType(math, allowedMathTypes, isHistogramBreakdown)).toBe(expected)
    })
})
