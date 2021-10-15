import { getMeanAndStandardDeviation } from './funnelUtils'

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
