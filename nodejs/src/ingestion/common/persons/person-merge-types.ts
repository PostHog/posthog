import { InternalPerson } from '~/types'

/**
 * Base class for all person merge errors
 */
export abstract class PersonMergeError extends Error {
    abstract readonly type: string

    constructor(message: string) {
        super(message)
        this.name = this.constructor.name
    }
}

/**
 * Error when merge limit is exceeded
 */
export class PersonMergeLimitExceededError extends PersonMergeError {
    readonly type = 'LIMIT_EXCEEDED' as const

    constructor(message: string) {
        super(message)
    }
}

/**
 * A merge response that carried no verdict for the source it was asked
 * about. Distinct from a settled failure: nothing is recorded against the
 * op id, so a retry can still reach a real answer, and the batch must fail
 * rather than ack a merge that never happened.
 */
export class PersonMergeResponseMismatchError extends PersonMergeError {
    readonly type = 'RESPONSE_MISMATCH' as const

    constructor(message: string) {
        super(message)
    }
}

/**
 * A merge call that failed with no verdict at all, so the saga's state is
 * unknowable from here. The batch must fail and redeliver: the saga replays
 * recorded outcomes idempotently, so redelivery converges where an ack
 * would lose the merge. Personhog-only; the Postgres merge never throws it.
 */
export class PersonMergeCallFailedError extends PersonMergeError {
    readonly type = 'CALL_FAILED' as const

    constructor(
        message: string,
        public readonly failure: unknown
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
 * Error when source person is not found during merge transaction
 */
export class SourcePersonNotFoundError extends PersonMergePersonNotFoundError {
    constructor(message: string) {
        super(message, 'source')
    }
}

/**
 * Error when target person is not found during merge transaction
 */
export class TargetPersonNotFoundError extends PersonMergePersonNotFoundError {
    constructor(message: string) {
        super(message, 'target')
    }
}

/**
 * Error when source person cannot be deleted due to concurrent distinct ID additions.
 * This occurs when a concurrent merge operation adds a distinct ID to the person being
 * deleted, causing a foreign key constraint violation. The retry will refresh the person
 * data and move all distinct IDs (including the newly added ones) before attempting deletion.
 */
export class SourcePersonHasDistinctIdsError extends PersonMergePersonNotFoundError {
    constructor(message: string) {
        super(message, 'source')
    }
}

/**
 * Result of a person merge operation
 */
export type PersonMergeResult =
    | {
          success: true
          person: InternalPerson | undefined
          kafkaAck: Promise<void>
          needsPersonUpdate: boolean
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
          limit: number
      }

/**
 * Helper function to create a successful merge result
 */
export function mergeSuccess(
    person: InternalPerson | undefined,
    kafkaAck: Promise<void>,
    needsPersonUpdate: boolean
): PersonMergeResult {
    return {
        success: true,
        person,
        kafkaAck,
        needsPersonUpdate,
    }
}

/**
 * Helper function to create a merge error result
 */
export function mergeError(error: PersonMergeError): PersonMergeResult {
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
export function determineMergeMode(
    personMergeMoveDistinctIdLimit: number,
    personMergeAsyncEnabled: boolean,
    personMergeSyncBatchSize: number
): MergeMode {
    // The limit becomes the saga's move_limit: a non-integer throws a
    // RangeError at request time and would fail every merge in the
    // deployment, so a bad value fails startup here instead.
    if (personMergeMoveDistinctIdLimit > 0 && !Number.isInteger(personMergeMoveDistinctIdLimit)) {
        throw new Error(`PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT must be an integer, got ${personMergeMoveDistinctIdLimit}`)
    }

    // If async merge is enabled, use async mode for over-limit merges
    if (personMergeAsyncEnabled && personMergeMoveDistinctIdLimit > 0) {
        return {
            type: 'ASYNC',
            limit: personMergeMoveDistinctIdLimit,
        }
    }

    // If no async and we have a limit, use limit mode (reject over-limit merges)
    if (personMergeMoveDistinctIdLimit > 0) {
        return {
            type: 'LIMIT',
            limit: personMergeMoveDistinctIdLimit,
        }
    }

    if (personMergeSyncBatchSize > 0) {
        return {
            type: 'SYNC',
            batchSize: personMergeSyncBatchSize,
        }
    }

    return {
        type: 'SYNC',
        batchSize: undefined,
    }
}
