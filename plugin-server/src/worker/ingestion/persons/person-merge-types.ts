import { InternalPerson } from '../../../types'

/**
 * Person Merge Result Types
 *
 * This module defines the result types for person merge operations, replacing
 * exception-based error handling with explicit result types. Actions are
 * determined by the consumer based on the error type.
 *
 * Design principles:
 * - Actions are handled by the caller, not embedded in the errors
 * - Each error type provides context for the caller to decide the action
 * - Type safety is enforced through TypeScript classes
 * - Helper functions provide convenient type guards and constructors
 */

/**
 * Actions that can be taken when a person merge operation fails
 * These are decided by the consumer based on the error type
 */
export type MergeAction = 'drop' | 'ignore' | 'dlq' | 'redirect'

/**
 * Base class for all person merge errors
 */
export abstract class PersonMergeError {
    abstract readonly type: string

    constructor(public readonly message: string) {}
}

/**
 * Error when merge limit is exceeded
 */
export class PersonMergeLimitExceededError extends PersonMergeError {
    readonly type = 'LIMIT_EXCEEDED' as const

    constructor(
        message: string,
        public readonly distinctIdCount: number
    ) {
        super(message)
    }
}

/**
 * Error when race condition is detected during merge
 */
export class PersonMergeRaceConditionError extends PersonMergeError {
    readonly type = 'RACE_CONDITION' as const

    constructor(message: string) {
        super(message)
    }
}

/**
 * Error when person is not found during merge
 */
export class PersonMergePersonNotFoundError extends PersonMergeError {
    readonly type = 'PERSON_NOT_FOUND' as const

    constructor(
        message: string,
        public readonly personType: 'source' | 'target'
    ) {
        super(message)
    }
}

/**
 * Error when merge is not allowed
 */
export class PersonMergeMergeNotAllowedError extends PersonMergeError {
    readonly type = 'MERGE_NOT_ALLOWED' as const

    constructor(message: string) {
        super(message)
    }
}

/**
 * Error when trying to merge with illegal distinct ID
 */
export class PersonMergeIllegalDistinctIdError extends PersonMergeError {
    readonly type = 'ILLEGAL_DISTINCT_ID' as const

    constructor(
        message: string,
        public readonly illegalDistinctId: string
    ) {
        super(message)
    }
}

/**
 * Result of a person merge operation
 */
export type PersonMergeResult =
    | {
          success: true
          person: InternalPerson
          kafkaAck: Promise<void>
      }
    | {
          success: false
          error: PersonMergeError
      }

/**
 * Merge modes for different processing strategies
 */
export type MergeMode =
    | {
          type: 'SYNC'
          batchSize: number | undefined // undefined = unlimited (process all distinct IDs in one query)
      }
    | {
          type: 'LIMIT'
          limit: number
      }
    | {
          type: 'ASYNC'
          topic: string
          limit: number
      }

/**
 * Type guard functions for MergeMode
 */
export function isSyncMode(mode: MergeMode): mode is Extract<MergeMode, { type: 'SYNC' }> {
    return mode.type === 'SYNC'
}

export function isLimitMode(mode: MergeMode): mode is Extract<MergeMode, { type: 'LIMIT' }> {
    return mode.type === 'LIMIT'
}

export function isAsyncMode(mode: MergeMode): mode is Extract<MergeMode, { type: 'ASYNC' }> {
    return mode.type === 'ASYNC'
}

/**
 * Helper function to create a successful merge result
 */
export function createMergeSuccess(person: InternalPerson, kafkaAck: Promise<void>): PersonMergeResult {
    return {
        success: true,
        person,
        kafkaAck,
    }
}

/**
 * Helper function to create a merge error result
 */
export function createMergeError(error: PersonMergeError): PersonMergeResult {
    return {
        success: false,
        error,
    }
}

/**
 * Helper function to create a default sync merge mode for testing
 */
export function createDefaultSyncMergeMode(): MergeMode {
    return {
        type: 'SYNC',
        batchSize: undefined, // unlimited
    }
}

/**
 * Helper function to determine merge mode based on hub configuration
 */
export function determineMergeMode(hub: {
    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: number
    PERSON_MERGE_ASYNC_ENABLED: boolean
    PERSON_MERGE_ASYNC_TOPIC: string
    PERSON_MERGE_SYNC_BATCH_SIZE: number
}): MergeMode {
    const limit = hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT === 0 ? undefined : hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT

    // If async merge is enabled and topic is configured, use async mode for over-limit merges
    if (hub.PERSON_MERGE_ASYNC_ENABLED && hub.PERSON_MERGE_ASYNC_TOPIC) {
        return {
            type: 'ASYNC',
            topic: hub.PERSON_MERGE_ASYNC_TOPIC,
            limit: limit || Number.MAX_SAFE_INTEGER,
        }
    }

    // If no async and we have a limit, use limit mode (reject over-limit merges)
    if (limit) {
        return {
            type: 'LIMIT',
            limit,
        }
    }

    // Default: sync mode with configurable batch size (0 = unlimited)
    return {
        type: 'SYNC',
        batchSize: hub.PERSON_MERGE_SYNC_BATCH_SIZE === 0 ? undefined : hub.PERSON_MERGE_SYNC_BATCH_SIZE,
    }
}
