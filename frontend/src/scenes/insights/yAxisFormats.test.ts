import { isYAxisFormat } from 'scenes/insights/yAxisFormat'

describe('y axis formats', () => {
    const testCases = [
        { candidate: null, expected: false },
        { candidate: 1, expected: false },
        { candidate: [], expected: false },
        { candidate: {}, expected: false },
        { candidate: 'tomato', expected: false },
        { candidate: 'numeric', expected: true },
        { candidate: 'percentage', expected: true },
        { candidate: 'duration', expected: true },
    ]
    testCases.forEach((testcase) => {
        it(`correctly detects that "${testcase.candidate}" ${
            testcase.expected ? 'is' : 'is _not_'
        } a valid y axis format`, () => {
            expect(isYAxisFormat(testcase.candidate)).toEqual(testcase.expected)
        })
    })
})
