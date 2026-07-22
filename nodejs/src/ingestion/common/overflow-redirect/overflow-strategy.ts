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
