import { PropertyFilterType, PropertyOperator, RecordingDurationFilter } from '~/types'
import { humanFriendlyDurationFilter } from './DurationFilter'

describe('DurationFilter', () => {
    describe('humanFriendlyDurationFilter', () => {
        it.each([
            [PropertyOperator.GreaterThan, 0, '> 0 seconds'],
            [PropertyOperator.GreaterThan, 1, '> 1 second'],
            [PropertyOperator.GreaterThan, 60, '> 1 minute'],
            [PropertyOperator.GreaterThan, 61, '> 61 seconds'],
            [PropertyOperator.GreaterThan, 120, '> 2 minutes'],
            [PropertyOperator.GreaterThan, 121, '> 121 seconds'],
            [PropertyOperator.GreaterThan, 3600, '> 1 hour'],
            [PropertyOperator.GreaterThan, 3601, '> 3601 seconds'],
            [PropertyOperator.GreaterThan, 3660, '> 61 minutes'],
            [PropertyOperator.LessThan, 0, '< 0 seconds'],
        ])('converts the value correctly', async (operator, value, expectation) => {
            const filter: RecordingDurationFilter = {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value,
                operator,
            }
            expect(humanFriendlyDurationFilter(filter)).toEqual(expectation)
        })
    })
})
