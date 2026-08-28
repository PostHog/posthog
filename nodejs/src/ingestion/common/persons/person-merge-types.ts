import { InternalPerson } from '~/types'

export abstract class PersonMergeError extends Error {
    abstract readonly type: string

    constructor(message: string) {
        super(message)
        this.name = this.constructor.name
    }
}

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
 * A merge call that failed with no verdict at all — transport failure,
 * a rejected request, an unclassifiable server error. The remote saga's
 * state is unknowable from here, so the batch must fail and redeliver:
 * the saga replays recorded outcomes idempotently, which makes the
 * redelivery converge where an ack would lose the merge. Personhog-only
 * by construction — the Postgres merge never wraps its errors in this,
 * so its failure handling is untouched.
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
 * A verdict this build has no name for, produced only by a backend a release
 * ahead. Neither settled nor transient: the merge may have happened and
 * redelivery reaches the same build until the roll finishes, so the event
 * goes to the DLQ where it stays replayable.
 */
export class PersonMergeUnknownOutcomeError extends PersonMergeError {
    readonly type = 'UNKNOWN_OUTCOME' as const

    constructor(
        message: string,
        public readonly outcome: string
    ) {
        super(message)
    }
}

export class PersonMergeRaceConditionError extends PersonMergeError {
    readonly type = 'RACE_CONDITION' as const

    constructor(message: string) {
        super(message)
    }
}

export class PersonMergePersonNotFoundError extends PersonMergeError {
    readonly type = 'PERSON_NOT_FOUND' as const

    constructor(
        message: string,
        public readonly personType: 'source' | 'target'
    ) {
        super(message)
    }
}

export class SourcePersonNotFoundError extends PersonMergePersonNotFoundError {
    constructor(message: string) {
        super(message, 'source')
    }
}

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

export function mergeError(error: PersonMergeError): PersonMergeResult {
    return {
        success: false,
        error,
    }
}

export function createDefaultSyncMergeMode(): MergeMode {
    return {
        type: 'SYNC',
        batchSize: undefined, // unlimited
    }
}

export function determineMergeMode(
    personMergeMoveDistinctIdLimit: number,
    personMergeAsyncEnabled: boolean,
    personMergeSyncBatchSize: number
): MergeMode {
    // The limit becomes the saga's move_limit, which it rejects unless it is
    // a positive integer, and which a non-integer turns into a RangeError at
    // request time. Both would fail every merge in the deployment, so a bad
    // value fails startup here instead — this runs once, at step construction.
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
