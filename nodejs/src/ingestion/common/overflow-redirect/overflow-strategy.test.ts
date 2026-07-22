import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import {
    EventRateOverflowStrategy,
    MergeEventRateOverflowStrategy,
    createAnalyticsOverflowStrategies,
} from './overflow-strategy'

describe('overflow strategies', () => {
    describe('EventRateOverflowStrategy', () => {
        it.each([['$pageview'], ['$identify'], [undefined]])('counts every event (%s) as one token', (event) => {
            const strategy = new EventRateOverflowStrategy()

            expect(strategy.countTokens(createTestEventHeaders({ event }))).toBe(1)
        })
    })

    describe('MergeEventRateOverflowStrategy', () => {
        it.each([
            ['$identify', 1],
            ['$create_alias', 1],
            ['$merge_dangerously', 1],
            ['$pageview', 0],
            ['identify', 0],
            ['$Identify', 0],
            [undefined, 0],
        ])('counts %s as %i tokens', (event, expected) => {
            const strategy = new MergeEventRateOverflowStrategy()

            expect(strategy.countTokens(createTestEventHeaders({ event }))).toBe(expected)
        })
    })

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
