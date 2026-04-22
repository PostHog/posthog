import { MessageKey } from '../../kafka/producer'

/** A Kafka message with a Buffer value, used by IngestionOutputs. */
export type IngestionOutputMessage = {
    value: Buffer | null
    key?: MessageKey
    headers?: Record<string, string>
}

/**
 * Controls how a dual-write output routes messages between primary and secondary targets.
 *
 * - `off`  — secondary is ignored; all messages go to primary only.
 * - `copy` — all messages go to primary; a percentage (based on key hash) is also copied to secondary.
 * - `move` — a percentage of messages (based on key hash) goes to secondary; the rest go to primary.
 *
 * Routing is deterministic per key (FNV-1a hash). Messages without a key are routed randomly.
 */
export type DualWriteMode = 'off' | 'copy' | 'move'
