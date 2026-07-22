import {
    EventRateOverflowStrategy,
    MergeEventRateOverflowStrategy,
    createAnalyticsOverflowStrategies,
} from './overflow-strategy'

describe('overflow strategies', () => {
    describe('createAnalyticsOverflowStrategies', () => {
        const baseConfig = {
            eventBucketCapacity: 1000,
            eventReplenishRate: 1,
            mergeEventBucketCapacity: 50,
            mergeEventReplenishRate: 0.1,
        }

        it('includes the merge strategy when its capacity is positive', () => {
            const strategies = createAnalyticsOverflowStrategies(baseConfig)

            expect(strategies).toHaveLength(2)
            expect(strategies[0].strategy).toBeInstanceOf(EventRateOverflowStrategy)
            expect(strategies[1].strategy).toBeInstanceOf(MergeEventRateOverflowStrategy)
        })

        it('omits the merge strategy entirely when its capacity is 0', () => {
            // A 0-capacity bucket would deny everything, so the strategy must be
            // omitted, not included with capacity 0
            const strategies = createAnalyticsOverflowStrategies({ ...baseConfig, mergeEventBucketCapacity: 0 })

            expect(strategies).toHaveLength(1)
            expect(strategies[0].strategy).toBeInstanceOf(EventRateOverflowStrategy)
        })
    })
})
