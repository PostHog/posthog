import { Message } from 'node-rdkafka'

import type { PluginsServerConfig } from '../../../types'
import { InvocationBuildStep } from '../../types'

/** A dead-letter record, read from its headers alone. */
export interface DeadLetterRecord {
    step: InvocationBuildStep | string
    reason: string
    timestamp: number
    teamId: number | null
    eventUuid: string | null
    hogFunctionIds: string[]
    hogFlowIds: string[]
    replayCount: number
}

export type ReplaySkipReason =
    | 'unreadable'
    | 'step'
    | 'window'
    | 'max_age'
    | 'team'
    | 'function'
    | 'reason'
    | 'exhausted'

export interface ReplayPolicy {
    steps: string[]
    from: number | null
    to: number | null
    maxAgeMs: number
    teamIds: number[]
    skipTeamIds: number[]
    hogFunctionIds: string[]
    reasonContains: string
    maxReplays: number
}

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

/**
 * Reads a record's headers without touching its payload.
 *
 * A replay run scans the whole topic to find the records its policy names, and a scan over millions
 * of parked events must not parse millions of event bodies to decide it wants none of them.
 */
export function readDeadLetterRecord(message: Message): DeadLetterRecord | null {
    const headers = headerValues(message)
    if (!headers.dlq_step || !message.value) {
        return null
    }

    const timestamp = Date.parse(headers.dlq_timestamp ?? '')
    const teamId = Number(headers.dlq_team_id)

    return {
        step: headers.dlq_step,
        reason: headers.dlq_reason ?? '',
        timestamp: Number.isNaN(timestamp) ? 0 : timestamp,
        teamId: Number.isFinite(teamId) && headers.dlq_team_id ? teamId : null,
        eventUuid: headers.dlq_event_uuid || null,
        hogFunctionIds: idList(headers.dlq_hog_function_ids),
        hogFlowIds: idList(headers.dlq_hog_flow_ids),
        replayCount: Number(headers.dlq_replay_count) || 0,
    }
}

/**
 * Decides whether one record is in scope for this run.
 *
 * A record out of scope is skipped and left where it is, never re-produced. Narrowing a replay is
 * how an operator delivers the events one bug lost without also delivering everything else parked
 * in the same window.
 */
export function shouldReplay(
    record: DeadLetterRecord | null,
    policy: ReplayPolicy,
    now: number
): { replay: true } | { replay: false; skipReason: ReplaySkipReason } {
    if (!record) {
        return { replay: false, skipReason: 'unreadable' }
    }
    if (record.replayCount >= policy.maxReplays) {
        return { replay: false, skipReason: 'exhausted' }
    }
    if (policy.steps.length && !policy.steps.includes(record.step)) {
        return { replay: false, skipReason: 'step' }
    }
    if (policy.from !== null && record.timestamp < policy.from) {
        return { replay: false, skipReason: 'window' }
    }
    if (policy.to !== null && record.timestamp > policy.to) {
        return { replay: false, skipReason: 'window' }
    }
    if (now - record.timestamp > policy.maxAgeMs) {
        return { replay: false, skipReason: 'max_age' }
    }
    if (record.teamId !== null && policy.skipTeamIds.includes(record.teamId)) {
        return { replay: false, skipReason: 'team' }
    }
    if (policy.teamIds.length && (record.teamId === null || !policy.teamIds.includes(record.teamId))) {
        return { replay: false, skipReason: 'team' }
    }
    if (policy.reasonContains && !record.reason.includes(policy.reasonContains)) {
        return { replay: false, skipReason: 'reason' }
    }
    if (policy.hogFunctionIds.length) {
        const named = [...record.hogFunctionIds, ...record.hogFlowIds]
        // An empty id list means every function of the team failed, so a run restricted to
        // specific functions cannot tell whether this record is one of them. Skip rather than
        // guess: replaying it would rebuild functions the operator did not ask for.
        if (!named.some((id) => policy.hogFunctionIds.includes(id))) {
            return { replay: false, skipReason: 'function' }
        }
    }
    return { replay: true }
}

/**
 * Restricts a rebuild to the sources the record names.
 *
 * This is what stops a replay double-delivering. An event that failed for one function out of five
 * was already delivered to the other four, and rebuilding all five would send those again. An empty
 * list means nothing was built the first time, so everything is in scope.
 */
export function replayTargetIds(record: DeadLetterRecord, policy: ReplayPolicy): Set<string> | null {
    const named = [...record.hogFunctionIds, ...record.hogFlowIds]
    if (!named.length) {
        return policy.hogFunctionIds.length ? new Set(policy.hogFunctionIds) : null
    }
    if (!policy.hogFunctionIds.length) {
        return new Set(named)
    }
    return new Set(named.filter((id) => policy.hogFunctionIds.includes(id)))
}

function numberList(value: string): number[] {
    return stringList(value)
        .map(Number)
        .filter((entry) => Number.isFinite(entry))
}

function stringList(value: string): string[] {
    return value
        .split(',')
        .map((entry) => entry.trim())
        .filter(Boolean)
}

export function readReplayPolicy(config: PluginsServerConfig): ReplayPolicy {
    const from = Date.parse(config.CDP_DLQ_REPLAY_FROM)
    const to = Date.parse(config.CDP_DLQ_REPLAY_TO)
    return {
        steps: stringList(config.CDP_DLQ_REPLAY_STEPS),
        from: Number.isNaN(from) ? null : from,
        to: Number.isNaN(to) ? null : to,
        maxAgeMs: config.CDP_DLQ_REPLAY_MAX_AGE_HOURS * 60 * 60 * 1000,
        teamIds: numberList(config.CDP_DLQ_REPLAY_TEAM_IDS),
        skipTeamIds: numberList(config.CDP_DLQ_REPLAY_SKIP_TEAM_IDS),
        hogFunctionIds: stringList(config.CDP_DLQ_REPLAY_HOG_FUNCTION_IDS),
        reasonContains: config.CDP_DLQ_REPLAY_REASON_CONTAINS,
        maxReplays: config.CDP_DLQ_REPLAY_MAX_REPLAYS,
    }
}
