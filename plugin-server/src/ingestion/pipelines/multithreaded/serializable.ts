/**
 * Interface for types that can be serialized to cross worker thread boundary.
 * Uses Uint8Array since that's what worker_threads transfers.
 */
export interface Serializable {
    serialize(): Uint8Array
}

/**
 * Static method interface for deserialization.
 * Implementations should have: static deserialize(data: Uint8Array): T
 */
export interface Deserializer<T> {
    deserialize(data: Uint8Array): T
}

/**
 * Result types matching PipelineResultType
 */
export enum WorkerResultType {
    OK = 0,
    DLQ = 1,
    DROP = 2,
    REDIRECT = 3,
}

/**
 * Warning from worker (same as PipelineWarning)
 */
export interface WorkerWarning {
    type: string
    details: Record<string, any>
    key?: string
    alwaysSend?: boolean
}

/**
 * Result from worker - mirrors PipelineResult but without sideEffects (can't pass callbacks)
 */
export type WorkerResult =
    | {
          type: WorkerResultType.OK
          correlationId: string
          value: Uint8Array // Serialized result value
          warnings: WorkerWarning[]
      }
    | {
          type: WorkerResultType.DLQ
          correlationId: string
          reason: string
          error?: string // Serialized error
          warnings: WorkerWarning[]
      }
    | {
          type: WorkerResultType.DROP
          correlationId: string
          reason: string
          warnings: WorkerWarning[]
      }
    | {
          type: WorkerResultType.REDIRECT
          correlationId: string
          reason: string
          topic: string
          preserveKey?: boolean
          awaitAck?: boolean
          warnings: WorkerWarning[]
      }

/**
 * Message types for worker communication protocol
 */
export type MainToWorkerMessage =
    | { type: 'event'; correlationId: string; data: Uint8Array }
    | { type: 'flush' } // Signal end of batch, wait for all results
    | { type: 'shutdown' }

export type WorkerToMainMessage =
    | { type: 'result'; result: WorkerResult }
    | { type: 'flush_complete' }
    | { type: 'ready' }
    | { type: 'error'; message: string; stack?: string }
