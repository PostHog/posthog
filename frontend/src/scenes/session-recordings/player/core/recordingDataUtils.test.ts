import { dayjs } from 'lib/dayjs'
import { generateInactiveSegmentsForRange } from './recordingDataUtils'

describe('generateInactiveSegmentsForRange', () => {
    it('happy case', () => {
        const startTime = dayjs('2023-03-22T14:46:06.461000Z')
        const endTime = startTime.add(60, 's')

        const generatedSegments = generateInactiveSegmentsForRange(+startTime, +endTime, '2', {
            1: {
                startTimeEpochMs: +startTime.subtract(30, 's'),
                endTimeEpochMs: +startTime.add(40, 's'),
            },
            2: {
                startTimeEpochMs: +startTime,
                endTimeEpochMs: +startTime.add(20, 's'),
            },
            3: {
                startTimeEpochMs: +startTime.subtract(35, 's'),
                endTimeEpochMs: +startTime.add(80, 's'),
            },
        })
        expect(generatedSegments).toMatchSnapshot()
    })
    it('for range that cannot be filled', () => {
        const startTime = dayjs('2023-03-22T14:46:06.461000Z')
        const endTime = startTime.add(60, 's')
        const generatedSegments = generateInactiveSegmentsForRange(+startTime, +endTime, '2', {
            2: {
                startTimeEpochMs: +startTime,
                endTimeEpochMs: +startTime.add(20, 's'),
            },
            3: {
                startTimeEpochMs: +startTime.subtract(35, 's'),
                endTimeEpochMs: +startTime.add(80, 's'),
            },
        })
        expect(generatedSegments).toMatchSnapshot()
    })
    it('for last segment', () => {
        const startTime = dayjs('2023-03-22T14:46:06.461000Z')
        const endTime = startTime.add(60, 's')
        const generatedSegments = generateInactiveSegmentsForRange(
            +startTime,
            +endTime,
            '2',
            {
                2: {
                    startTimeEpochMs: +startTime,
                    endTimeEpochMs: +startTime.add(20, 's'),
                },
            },
            false,
            true
        )
        expect(generatedSegments).toMatchSnapshot()
    })
})
