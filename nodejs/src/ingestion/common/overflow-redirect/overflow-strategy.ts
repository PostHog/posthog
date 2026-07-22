import { EventHeaders } from '~/types'

/**
 * A pluggable overflow condition for the main-lane overflow redirect.
 *
 * Strategies are pure classifiers: they only decide how many tokens an event
 * consumes from their bucket. All state (the token buckets, keyed on
 * token:distinct_id) is owned by the redirect service, one bucket set per
 * strategy. A key is redirected to overflow when any strategy's bucket is
 * exhausted.
 */
export interface OverflowStrategy {
    /** Tokens this event consumes from the strategy's bucket; 0 = not counted. */
    countTokens(headers: EventHeaders): number
}

/** Pairs a strategy with the limits for its token buckets. */
export interface OverflowStrategyEntry {
    strategy: OverflowStrategy
    bucketCapacity: number
    replenishRate: number
}

/** Counts every event: the overall event-rate overflow condition. */
export class EventRateOverflowStrategy implements OverflowStrategy {
    countTokens(): number {
        return 1
    }
}

/** Events that can trigger a person merge - the expensive person-processing path. */
const MERGE_EVENT_NAMES = new Set(['$identify', '$create_alias', '$merge_dangerously'])

export function isMergeEvent(eventName: string | undefined): boolean {
    return eventName !== undefined && MERGE_EVENT_NAMES.has(eventName)
}

/**
 * Counts only person-merge events, so merge-heavy actors overflow at a
 * dedicated (much lower) rate than the overall event rate. Events without an
 * event name header are not counted (fail open).
 */
export class MergeEventRateOverflowStrategy implements OverflowStrategy {
    countTokens(headers: EventHeaders): number {
        return isMergeEvent(headers.event) ? 1 : 0
    }
}

/**
 * Strategy set for the analytics events pipeline: overall event rate, plus a
 * merge-event rate condition when enabled (a merge bucket capacity of 0
 * disables it - the strategy is omitted entirely rather than denying all).
 */
export function createAnalyticsOverflowStrategies(config: {
    eventBucketCapacity: number
    eventReplenishRate: number
    mergeEventBucketCapacity: number
    mergeEventReplenishRate: number
}): OverflowStrategyEntry[] {
    const strategies: OverflowStrategyEntry[] = [
        {
            strategy: new EventRateOverflowStrategy(),
            bucketCapacity: config.eventBucketCapacity,
            replenishRate: config.eventReplenishRate,
        },
    ]
    if (config.mergeEventBucketCapacity > 0) {
        strategies.push({
            strategy: new MergeEventRateOverflowStrategy(),
            bucketCapacity: config.mergeEventBucketCapacity,
            replenishRate: config.mergeEventReplenishRate,
        })
    }
    return strategies
}

/**
 * Metrics label for a strategy, derived from its class name
 * (e.g. EventRateOverflowStrategy -> event_rate). The class name is thereby
 * part of the metrics contract: renaming a strategy renames its label.
 */
export function overflowStrategyLabel(strategy: OverflowStrategy): string {
    return strategy.constructor.name
        .replace(/OverflowStrategy$/, '')
        .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
        .toLowerCase()
}
