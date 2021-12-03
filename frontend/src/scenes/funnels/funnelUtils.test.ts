import { EMPTY_BREAKDOWN_VALUES, getBreakdownStepValues, getMeanAndStandardDeviation } from './funnelUtils'

describe('getMeanAndStandardDeviation', () => {
    const arrayToExpectedValues: [number[], number[]][] = [
        [
            [1, 2, 3, 4, 5],
            [3, Math.sqrt(2)],
        ],
        [
            [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            [5.5, Math.sqrt(8.25)],
        ],
        [[1], [1, 0]],
        [[], [0, 100]],
        [
            [1, 1, 1, 1, 1],
            [1, 0],
        ],
        [
            [1, 1, 1, 1, 5],
            [1.8, 1.6],
        ],
    ]

    arrayToExpectedValues.forEach(([array, expected]) => {
        it(`expect mean and deviation for array=${array} to equal ${expected}`, () => {
            const [mean, stdDev] = getMeanAndStandardDeviation(array)
            expect(mean).toBeCloseTo(expected[0])
            expect(stdDev).toBeCloseTo(expected[1])
        })
    })
})

describe('getBreakdownStepValues()', () => {
    it('is baseline breakdown', () => {
        expect(getBreakdownStepValues({ breakdown: 'blah', breakdown_value: 'Blah' }, 21, true)).toStrictEqual({
            rowKey: 'baseline_0',
            breakdown: ['baseline'],
            breakdown_value: ['Baseline'],
        })
    })
    it('breakdowns are well formed arrays', () => {
        expect(
            getBreakdownStepValues({ breakdown: ['blah', 'woof'], breakdown_value: ['Blah', 'Woof'] }, 21)
        ).toStrictEqual({
            rowKey: 'blah_woof_21',
            breakdown: ['blah', 'woof'],
            breakdown_value: ['Blah', 'Woof'],
        })
    })
    it('breakdowns are empty arrays', () => {
        expect(getBreakdownStepValues({ breakdown: [], breakdown_value: [] }, 21)).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdowns are arrays with empty string', () => {
        expect(getBreakdownStepValues({ breakdown: [''], breakdown_value: [''] }, 21)).toStrictEqual(
            EMPTY_BREAKDOWN_VALUES
        )
    })
    it('breakdowns are arrays with null', () => {
        expect(
            getBreakdownStepValues(
                {
                    breakdown: [null as unknown as string | number],
                    breakdown_value: [null as unknown as string | number],
                },
                21
            )
        ).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdowns are arrays with undefined', () => {
        expect(
            getBreakdownStepValues(
                {
                    breakdown: [undefined as unknown as string | number],
                    breakdown_value: [undefined as unknown as string | number],
                },
                21
            )
        ).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdown is string', () => {
        expect(getBreakdownStepValues({ breakdown: 'blah', breakdown_value: 'Blah' }, 21)).toStrictEqual({
            rowKey: 'blah_21',
            breakdown: ['blah'],
            breakdown_value: ['Blah'],
        })
    })
    it('breakdown is empty string', () => {
        expect(getBreakdownStepValues({ breakdown: '', breakdown_value: '' }, 21)).toStrictEqual(EMPTY_BREAKDOWN_VALUES)
    })
    it('breakdown is undefined string', () => {
        expect(getBreakdownStepValues({ breakdown: undefined, breakdown_value: undefined }, 21)).toStrictEqual(
            EMPTY_BREAKDOWN_VALUES
        )
    })
    it('breakdown is null string', () => {
        expect(getBreakdownStepValues({ breakdown: null, breakdown_value: null }, 21)).toStrictEqual(
            EMPTY_BREAKDOWN_VALUES
        )
    })
})
