import { MessageKey } from '../../kafka/producer'

/** A Kafka message with a Buffer value, used by IngestionOutputs. */
export type IngestionOutputMessage = {
    value: Buffer | null
    key?: MessageKey
    headers?: Record<string, string>
    teamId?: number
}

/**
 * Controls how a dual-write output routes messages between primary and secondary targets.
 *
 * Percentage-based modes (route by hash of message key):
 * - `off`  — secondary is ignored; all messages go to primary only.
 * - `copy` — all messages go to primary; a percentage (based on key hash) is also copied to secondary.
 * - `move` — a percentage of messages (based on key hash) goes to secondary; the rest go to primary.
 *
 * Team-denylist modes (route by the message's `teamId`):
 * - `copy_team_denylist` — team IDs in the denylist go to primary only.
 *   All other teams go to primary and secondary.
 * - `move_team_denylist` — team IDs in the denylist go to primary only.
 *   All other teams go to secondary only.
 *
 * Messages without `teamId` always stay on primary in denylist modes.
 *
 * Routing is deterministic per key (FNV-1a hash) for percentage modes.
 * Messages without a key are routed randomly in percentage modes.
 */
export type DualWriteMode = 'off' | 'copy' | 'move' | 'copy_team_denylist' | 'move_team_denylist'
