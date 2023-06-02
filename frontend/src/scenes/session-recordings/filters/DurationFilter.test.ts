import { DurationTypeFilter, PropertyFilterType, PropertyOperator, RecordingDurationFilter } from '~/types'
import { humanFriendlyDurationFilter } from './DurationFilter'

describe('DurationFilter', () => {
    describe('humanFriendlyDurationFilter', () => {
        it.each([
            [PropertyOperator.GreaterThan, 0, 'duration', '> 0 seconds'],
            [PropertyOperator.GreaterThan, 1, 'duration', '> 1 second'],
            [PropertyOperator.GreaterThan, 60, 'duration', '> 1 minute'],
            [PropertyOperator.GreaterThan, 61, 'duration', '> 61 seconds'],
            [PropertyOperator.GreaterThan, 120, 'duration', '> 2 minutes'],
            [PropertyOperator.GreaterThan, 121, 'duration', '> 121 seconds'],
            [PropertyOperator.GreaterThan, 3600, 'duration', '> 1 hour'],
            [PropertyOperator.GreaterThan, 3601, 'duration', '> 3601 seconds'],
            [PropertyOperator.GreaterThan, 3660, 'duration', '> 61 minutes'],
            [PropertyOperator.LessThan, 0, 'duration', '< 0 seconds'],
            [PropertyOperator.GreaterThan, 0, 'active_seconds', '> 0 active seconds'],
            [PropertyOperator.GreaterThan, 1, 'active_seconds', '> 1 active second'],
            [PropertyOperator.GreaterThan, 60, 'active_seconds', '> 1 active minute'],
            [PropertyOperator.GreaterThan, 61, 'active_seconds', '> 61 active seconds'],
            [PropertyOperator.GreaterThan, 120, 'active_seconds', '> 2 active minutes'],
            [PropertyOperator.GreaterThan, 121, 'active_seconds', '> 121 active seconds'],
            [PropertyOperator.GreaterThan, 3600, 'active_seconds', '> 1 active hour'],
            [PropertyOperator.GreaterThan, 3601, 'active_seconds', '> 3601 active seconds'],
            [PropertyOperator.GreaterThan, 3660, 'active_seconds', '> 61 active minutes'],
            [PropertyOperator.LessThan, 0, 'active_seconds', '< 0 active seconds'],
        ])('converts the value correctly for total duration', async (operator, value, durationType, expectation) => {
            const filter: RecordingDurationFilter = {
                type: PropertyFilterType.Recording,
                key: 'duration',
                value,
                operator,
            }
            expect(humanFriendlyDurationFilter(filter, durationType as DurationTypeFilter)).toEqual(expectation)
        })
    })
})
