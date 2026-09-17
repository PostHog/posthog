import { Message } from 'node-rdkafka'

import { parseJSON } from '~/common/utils/json-parse'

import type { RawClickHouseEvent } from '../../../types'

/**
 * A dead-letter record, read from its headers alone.
 *
 * Only the two id lists are here. The producer writes the step, reason, team and source position
 * too, but those exist for a person reading the topic, and reading them into this type would
 * suggest the worker branches on them.
 */
export interface DeadLetterRecord {
    hogFunctionIds: string[]
    hogFlowIds: string[]
    /** Which kinds this record's replay may rebuild. Empty means nothing was built, so both. */
    kinds: SourceKind[]
}

export type SourceKind = 'hog_function' | 'hog_flow'

function headerValues(message: Message): Record<string, string> {
    const values: Record<string, string> = {}
    for (const header of message.headers ?? []) {
        for (const [key, value] of Object.entries(header)) {
            if (value === undefined) {
                continue
            }
            values[key] = Buffer.isBuffer(value) ? value.toString() : String(value)
        }
    }
    return values
}

function idList(value: string | undefined): string[] {
    return (value ?? '')
        .split(',')
        .map((id) => id.trim())
        .filter(Boolean)
}

/** Reads a record's headers without touching its payload. `dlq_step` marks it as one of ours. */
export function readDeadLetterRecord(message: Message): DeadLetterRecord | null {
    const headers = headerValues(message)
    if (!headers.dlq_step || !message.value) {
        return null
    }

    return {
        hogFunctionIds: idList(headers.dlq_hog_function_ids),
        hogFlowIds: idList(headers.dlq_hog_flow_ids),
        kinds: idList(headers.dlq_kinds).filter(
            (kind): kind is SourceKind => kind === 'hog_function' || kind === 'hog_flow'
        ),
    }
}

/**
 * Restricts a rebuild to the sources the record names.
 *
 * This is what stops a replay double-delivering. An event that failed for one function out of five
 * was already delivered to the other four, and rebuilding all five would send those again. An empty
 * list means nothing was built the first time, so everything is in scope.
 */
export function replayTargetIds(record: DeadLetterRecord): Set<string> | null {
    const named = [...record.hogFunctionIds, ...record.hogFlowIds]
    return named.length ? new Set(named) : null
}

/**
 * Which pipelines may rebuild for this record.
 *
 * Null is every kind, and only right when nothing was built the first time. A `process` failure
 * names its kind but no id, because the two pipelines run against the same event: one can queue its
 * invocations while the other throws, and rebuilding both would re-deliver what already went out.
 */
export function replayTargetKinds(record: DeadLetterRecord): Set<SourceKind> | null {
    return record.kinds.length ? new Set(record.kinds) : null
}

/** Reads a parked payload. Null when the bytes are not an event this worker can rebuild. */
export function readParkedEvent(message: Message): RawClickHouseEvent | null {
    if (!message.value) {
        return null
    }
    const event = parseJSON(message.value.toString()) as RawClickHouseEvent
    return event.team_id ? event : null
}
