import { InternalPerson } from '../../../types'

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
          topic: string
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
export function determineMergeMode(hub: {
    PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT: number
    PERSON_MERGE_ASYNC_ENABLED: boolean
    PERSON_MERGE_ASYNC_TOPIC: string
    PERSON_MERGE_SYNC_BATCH_SIZE: number
}): MergeMode {
    // If async merge is enabled and topic is configured, use async mode for over-limit merges
    if (hub.PERSON_MERGE_ASYNC_ENABLED && hub.PERSON_MERGE_ASYNC_TOPIC && hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT > 0) {
        return {
            type: 'ASYNC',
            topic: hub.PERSON_MERGE_ASYNC_TOPIC,
            limit: hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
        }
    }

    // If no async and we have a limit, use limit mode (reject over-limit merges)
    if (hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT > 0) {
        return {
            type: 'LIMIT',
            limit: hub.PERSON_MERGE_MOVE_DISTINCT_ID_LIMIT,
        }
    }

    if (hub.PERSON_MERGE_SYNC_BATCH_SIZE > 0) {
        return {
            type: 'SYNC',
            batchSize: hub.PERSON_MERGE_SYNC_BATCH_SIZE,
        }
    }

    return {
        type: 'SYNC',
        batchSize: undefined,
    }
}
