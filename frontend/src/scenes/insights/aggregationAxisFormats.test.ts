import { formatAggregationAxisValue, AggregationAxisFormat } from 'scenes/insights/aggregationAxisFormat'

describe('formatAggregationAxisValue', () => {
    const formatTestcases = [
        { candidate: 34, format: 'duration', expected: '34s' },
        { candidate: 340, format: 'duration', expected: '5m 40s' },
        { candidate: 3940, format: 'duration', expected: '1h 5m 40s' },
        { candidate: 3.944, format: 'percentage', expected: '3.94%' },
        { candidate: 3.956, format: 'percentage', expected: '3.96%' },
        { candidate: 3940, format: 'percentage', expected: '3 940%' },
        { candidate: 34, format: 'numeric', expected: '34' },
        { candidate: 394, format: 'numeric', expected: '394' },
        { candidate: 3940, format: 'numeric', expected: '3.94K' },
    ]
    formatTestcases.forEach((testcase) => {
        it(`correctly formats "${testcase.candidate}" as ${testcase.expected} when it is a ${testcase.format}`, () => {
            expect(formatAggregationAxisValue(testcase.format as AggregationAxisFormat, testcase.candidate)).toEqual(
                testcase.expected
            )
        })
    })
})
