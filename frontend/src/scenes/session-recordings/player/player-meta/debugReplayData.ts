import { EventType } from 'posthog-js/rrweb-types'

import { RRWebRecordingConsoleLogPayload, RecordingSnapshot } from '~/types'

import { getPerformanceEvents } from '../../apm/performance-event-utils'
import { ExportedSessionRecordingFileV2 } from '../../file-playback/types'

/** The context block rides on every message of the conversation, so the recording data gets a fixed budget. */
export const DEBUG_REPLAY_DATA_MAX_CHARS = 64_000

const CONSOLE_LOG_PLUGIN_NAME = 'rrweb/console@1'
const MAX_MESSAGE_CHARS = 500
const MAX_URL_CHARS = 300

interface DebugReplayEntry {
    t: number
    kind: 'page' | 'console' | 'network' | 'custom'
    [field: string]: unknown
}

interface PrioritizedEntry {
    entry: DebugReplayEntry
    important: boolean
}

function truncate(value: string, maxChars: number): string {
    return value.length > maxChars ? `${value.slice(0, maxChars)}…[truncated]` : value
}

function relativeSeconds(timestampMs: number, startMs: number): number {
    return Math.max(0, Math.round((timestampMs - startMs) / 100) / 10)
}

function snapshotToEntries(snapshot: RecordingSnapshot, startMs: number): PrioritizedEntry[] {
    const t = relativeSeconds(snapshot.timestamp, startMs)

    if (snapshot.type === EventType.Meta) {
        const { href, width, height } = snapshot.data
        return [
            {
                entry: { t, kind: 'page', url: truncate(href ?? '', MAX_URL_CHARS), viewport: `${width}x${height}` },
                important: true,
            },
        ]
    }

    if (snapshot.type === EventType.Custom) {
        const payload = JSON.stringify(snapshot.data.payload ?? null) ?? 'null'
        return [
            {
                entry: { t, kind: 'custom', tag: snapshot.data.tag, payload: truncate(payload, MAX_URL_CHARS) },
                important: false,
            },
        ]
    }

    if (snapshot.type !== EventType.Plugin) {
        return []
    }

    if (snapshot.data.plugin === CONSOLE_LOG_PLUGIN_NAME) {
        const data = snapshot.data.payload as RRWebRecordingConsoleLogPayload | undefined
        if (!data) {
            return []
        }
        const lines = (Array.isArray(data.payload) ? data.payload : [data.payload]).filter((x) => !!x)
        const isProblem = data.level === 'error' || data.level === 'warn'
        const entry: DebugReplayEntry = {
            t,
            kind: 'console',
            level: data.level,
            message: truncate(lines.join('\n'), MAX_MESSAGE_CHARS),
        }
        if (data.level === 'error' && Array.isArray(data.trace) && data.trace.length > 0) {
            entry.trace = data.trace.slice(0, 3).map((line) => truncate(String(line), MAX_URL_CHARS))
        }
        return [{ entry, important: isProblem }]
    }

    return []
}

export function buildDebugReplayData(
    exported: ExportedSessionRecordingFileV2,
    maxChars: number = DEBUG_REPLAY_DATA_MAX_CHARS
): string {
    const snapshots = exported.data.snapshots ?? []
    const startMs = snapshots.reduce((min, snapshot) => Math.min(min, snapshot.timestamp), Infinity)
    const endMs = snapshots.reduce((max, snapshot) => Math.max(max, snapshot.timestamp), -Infinity)

    const snapshotCounts: Record<string, number> = {}
    const prioritized: PrioritizedEntry[] = []
    for (const snapshot of snapshots) {
        const typeName = EventType[snapshot.type] ?? String(snapshot.type)
        snapshotCounts[typeName] = (snapshotCounts[typeName] ?? 0) + 1
        prioritized.push(...snapshotToEntries(snapshot, startMs))
    }
    // The recorder has two network payload formats. The inspector's parser reads both.
    for (const request of getPerformanceEvents({ all: snapshots })) {
        const status = typeof request.response_status === 'number' ? request.response_status : undefined
        prioritized.push({
            entry: {
                t: relativeSeconds(new Date(request.timestamp).valueOf(), startMs),
                kind: 'network',
                method: request.method,
                url: truncate(String(request.name ?? ''), MAX_URL_CHARS),
                status,
                initiator: request.initiator_type,
                duration_ms: typeof request.duration === 'number' ? Math.round(request.duration) : undefined,
            },
            // Status 0 is how the browser reports a request that never got a response.
            important: status !== undefined && (status >= 400 || status === 0),
        })
    }
    prioritized.sort((a, b) => a.entry.t - b.entry.t)

    const base = {
        session_id: exported.data.id,
        start_time: snapshots.length > 0 ? new Date(startMs).toISOString() : null,
        duration_seconds: snapshots.length > 0 ? Math.round((endMs - startMs) / 1000) : 0,
        snapshot_counts: snapshotCounts,
    }

    let remaining =
        maxChars - JSON.stringify({ ...base, timeline: [], omitted: { problems: 0, other: 0 } }).length - 200
    const kept = new Set<PrioritizedEntry>()
    for (const important of [true, false]) {
        for (const item of prioritized) {
            if (item.important !== important) {
                continue
            }
            const cost = JSON.stringify(item.entry).length + 1
            if (cost > remaining) {
                continue
            }
            remaining -= cost
            kept.add(item)
        }
    }

    const omitted = prioritized.filter((item) => !kept.has(item))
    return JSON.stringify({
        ...base,
        timeline: prioritized.filter((item) => kept.has(item)).map((item) => item.entry),
        ...(omitted.length > 0
            ? {
                  omitted: {
                      problems: omitted.filter((item) => item.important).length,
                      other: omitted.filter((item) => !item.important).length,
                      note: 'Entries were left out to fit the size limit. Query the session for the rest.',
                  },
              }
            : {}),
    })
}
