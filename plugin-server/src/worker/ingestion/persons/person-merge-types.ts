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
export type MergeMode = 'SYNC' | 'ASYNC' | 'BATCH'

/**
 * Helper function to determine the recommended action for an error type
 * This is a suggestion - the actual action is decided by the consumer
 */
export function getRecommendedAction(error: PersonMergeError): MergeAction {
    switch (error.type) {
        case 'LIMIT_EXCEEDED':
            return 'redirect'
        case 'RACE_CONDITION':
        case 'PERSON_NOT_FOUND':
        case 'MERGE_NOT_ALLOWED':
        case 'ILLEGAL_DISTINCT_ID':
            return 'ignore'
        default:
            return 'ignore'
    }
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
