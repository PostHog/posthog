import {
    expectedRunningTime,
    minimumSampleSizePerVariant,
    recommendedExposureForCountData,
} from './legacyExperimentCalculations'

describe('experimentCalculations', () => {
    describe('minimumSampleSizePerVariant', () => {
        it('given an mde, calculates correct sample size', () => {
            // Using the rule of thumb: sampleSize = 16 * sigma^2 / (mde^2)
            expect(minimumSampleSizePerVariant(30, 20)).toEqual(29)

            expect(minimumSampleSizePerVariant(30, 40)).toEqual(43)

            expect(minimumSampleSizePerVariant(30, 0)).toEqual(0)
        })
    })

    describe('expectedRunningTime', () => {
        it('given sample size and entrants, calculates correct running time', () => {
            // 500 entrants over 14 days, 1000 sample size, so need twice the time
            expect(expectedRunningTime(500, 1000)).toEqual(28)

            // 500 entrants over 14 days, 250 sample size, so need half the time
            expect(expectedRunningTime(500, 250)).toEqual(7)

            // 0 entrants over 14 days, so infinite running time
            expect(expectedRunningTime(0, 1000)).toEqual(Infinity)

            // Custom duration
            expect(expectedRunningTime(500, 1000, 7)).toEqual(14)
        })
    })

    describe('recommendedExposureForCountData', () => {
        it('given control count data, calculates correct exposure time', () => {
            // Using formula: 4 / (sqrt(lambda1/days) - sqrt(lambda2/days))^2

            // 1000 count over 14 days
            expect(recommendedExposureForCountData(30, 1000)).toEqual(2.8)

            // 10,000 count over 14 days - 10x count, so 1/10th running time
            expect(recommendedExposureForCountData(30, 10000)).toEqual(0.3)

            // 0 count, so should be Infinity (can't calculate with zero)
            expect(recommendedExposureForCountData(30, 0)).toEqual(Infinity)
        })
    })
})
