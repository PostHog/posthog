import { colonDelimitedDuration, eventToDescription } from 'lib/utils'

import { InspectorListItem } from './playerInspectorLogic'

export type InspectorSerializeFormat = 'json' | 'text'

export const BULK_ITEM_LIMIT = 10000

export const SYNTHETIC_INSPECTOR_ITEM_TYPES: ReadonlySet<InspectorListItem['type']> = new Set([
    'inspector-summary',
    'inactivity',
    'session-change',
])

export function isExportableInspectorItem(item: InspectorListItem): boolean {
    return !SYNTHETIC_INSPECTOR_ITEM_TYPES.has(item.type)
}

function formatRelativeTime(timeInRecording: number): string {
    if (timeInRecording < 0) {
        return 'load'
    }
    return colonDelimitedDuration(timeInRecording / 1000, null)
}

function timestampPrefix(item: InspectorListItem): string {
    const relative = formatRelativeTime(item.timeInRecording)
    const iso = item.timestamp?.toISOString?.() ?? ''
    return iso ? `[${relative} | ${iso}]` : `[${relative}]`
}

function safeStringify(value: unknown, pretty: boolean = true): string {
    try {
        return pretty ? JSON.stringify(value, null, 2) : JSON.stringify(value)
    } catch {
        return String(value)
    }
}

function eventToText(item: Extract<InspectorListItem, { type: 'events' }>): string {
    const description = eventToDescription(item.data)
    const head = `${timestampPrefix(item)} event ${item.data.event}`
    return description && description !== item.data.event ? `${head} — ${description}` : head
}

function consoleToText(item: Extract<InspectorListItem, { type: 'console' }>): string {
    const { level, content, count, lines, trace } = item.data
    const header = `${timestampPrefix(item)} ${level.toUpperCase()} ${content}${count && count > 1 ? ` (x${count})` : ''}`
    const extra: string[] = []
    if (lines && lines.length > 1) {
        extra.push(...lines.slice(1))
    }
    if (trace && trace.length) {
        extra.push(...trace)
    }
    return extra.length ? `${header}\n${extra.join('\n')}` : header
}

function networkToText(item: Extract<InspectorListItem, { type: 'network' }>): string {
    const { name, response_status, duration, initiator_type, method } = item.data
    const parts = [timestampPrefix(item), 'network']
    if (method) {
        parts.push(method)
    }
    parts.push(name ?? '(unnamed)')
    if (response_status != null) {
        parts.push(`-> ${response_status}`)
    }
    if (duration != null) {
        parts.push(`(${Math.round(duration)}ms)`)
    }
    if (initiator_type) {
        parts.push(`[${initiator_type}]`)
    }
    return parts.join(' ')
}

function logToText(item: Extract<InspectorListItem, { type: 'logs' }>): string {
    const { severity_text, body, attributes } = item.data
    const head = `${timestampPrefix(item)} ${(severity_text ?? '').toUpperCase()} ${body}`
    const attrEntries = Object.entries(attributes ?? {})
    if (!attrEntries.length) {
        return head
    }
    const attrLines = attrEntries.map(([k, v]) => `  ${k}=${typeof v === 'string' ? v : safeStringify(v)}`)
    return `${head}\n${attrLines.join('\n')}`
}

function commentToText(item: Extract<InspectorListItem, { type: 'comment' }>): string {
    const body =
        item.source === 'comment'
            ? (item.data.content ?? '(empty comment)')
            : `${item.data.comment} — from notebook "${item.data.notebookTitle}"`
    return `${timestampPrefix(item)} comment ${body}`
}

function doctorToText(item: Extract<InspectorListItem, { type: 'doctor' }>): string {
    const head = `${timestampPrefix(item)} doctor ${item.tag}`
    if (!item.data || !Object.keys(item.data).length) {
        return head
    }
    return `${head}\n${safeStringify(item.data)}`
}

function appStateToText(item: Extract<InspectorListItem, { type: 'app-state' }>): string {
    const head = `${timestampPrefix(item)} app-state ${item.action}`
    if (!item.stateEvent) {
        return head
    }
    return `${head}\n${safeStringify(item.stateEvent)}`
}

function offlineToText(item: Extract<InspectorListItem, { type: 'offline-status' }>): string {
    return `${timestampPrefix(item)} ${item.offline ? 'browser went offline' : 'browser returned online'}`
}

function visibilityToText(item: Extract<InspectorListItem, { type: 'browser-visibility' }>): string {
    return `${timestampPrefix(item)} browser tab became ${item.status}`
}

function inactivityToText(item: Extract<InspectorListItem, { type: 'inactivity' }>): string {
    return `${timestampPrefix(item)} inactivity ${Math.round(item.durationMs / 1000)}s`
}

function sessionChangeToText(item: Extract<InspectorListItem, { type: 'session-change' }>): string {
    return `${timestampPrefix(item)} ${item.tag}${item.data?.nextSessionId ? ` -> ${item.data.nextSessionId}` : ''}`
}

function summaryToText(item: Extract<InspectorListItem, { type: 'inspector-summary' }>): string {
    return `${timestampPrefix(item)} summary clicks=${item.clickCount ?? 0} keys=${item.keypressCount ?? 0} errors=${item.errorCount ?? 0}`
}

function itemToText(item: InspectorListItem): string {
    switch (item.type) {
        case 'events':
            return eventToText(item)
        case 'console':
            return consoleToText(item)
        case 'network':
            return networkToText(item)
        case 'logs':
            return logToText(item)
        case 'comment':
            return commentToText(item)
        case 'doctor':
            return doctorToText(item)
        case 'app-state':
            return appStateToText(item)
        case 'offline-status':
            return offlineToText(item)
        case 'browser-visibility':
            return visibilityToText(item)
        case 'inactivity':
            return inactivityToText(item)
        case 'session-change':
            return sessionChangeToText(item)
        case 'inspector-summary':
            return summaryToText(item)
        default: {
            const _exhaustive: never = item
            return String(_exhaustive)
        }
    }
}

function itemToJsonObject(item: InspectorListItem): Record<string, unknown> {
    const base = {
        type: item.type,
        timestamp: item.timestamp?.toISOString?.() ?? null,
        timeInRecording: item.timeInRecording,
        windowNumber: item.windowNumber ?? null,
        highlightColor: item.highlightColor ?? null,
    }
    switch (item.type) {
        case 'events':
        case 'console':
        case 'network':
        case 'logs':
        case 'comment':
            return { ...base, data: item.data }
        case 'doctor':
            return { ...base, tag: item.tag, data: item.data ?? null }
        case 'app-state':
            return { ...base, action: item.action, stateEvent: item.stateEvent ?? null }
        case 'offline-status':
            return { ...base, offline: item.offline }
        case 'browser-visibility':
            return { ...base, status: item.status }
        case 'inactivity':
            return { ...base, durationMs: item.durationMs }
        case 'session-change':
            return { ...base, tag: item.tag, data: item.data }
        case 'inspector-summary':
            return {
                ...base,
                clickCount: item.clickCount,
                keypressCount: item.keypressCount,
                errorCount: item.errorCount,
            }
        default: {
            const _exhaustive: never = item
            return { ...(_exhaustive as object) }
        }
    }
}

export function serializeInspectorItem(item: InspectorListItem, format: InspectorSerializeFormat): string {
    if (format === 'json') {
        return safeStringify(itemToJsonObject(item))
    }
    return itemToText(item)
}

export interface BulkSerializeOptions {
    sessionId?: string
    recordingStart?: string
    filterSummary?: string
}

export interface BulkSerializeResult {
    output: string
    itemCount: number
    truncated: boolean
}

export function serializeInspectorItems(
    items: InspectorListItem[],
    format: InspectorSerializeFormat,
    opts: BulkSerializeOptions = {}
): BulkSerializeResult {
    // Single pass: filter synthetic items and cap to BULK_ITEM_LIMIT.
    const sliced: InspectorListItem[] = []
    let exportableCount = 0
    let truncated = false
    for (const item of items) {
        if (!isExportableInspectorItem(item)) {
            continue
        }
        exportableCount++
        if (sliced.length < BULK_ITEM_LIMIT) {
            sliced.push(item)
        } else {
            truncated = true
        }
    }

    if (format === 'json') {
        const payload = {
            session_id: opts.sessionId ?? null,
            recording_start: opts.recordingStart ?? null,
            filter_summary: opts.filterSummary ?? null,
            item_count: sliced.length,
            truncated,
            items: sliced.map(itemToJsonObject),
        }
        // Bulk JSON skips indentation — clipboard payloads at 10k items can be multi-MB pretty-printed.
        return { output: safeStringify(payload, false), itemCount: sliced.length, truncated }
    }

    const headerLines: string[] = []
    if (opts.sessionId) {
        headerLines.push(`# Session: ${opts.sessionId}`)
    }
    if (opts.recordingStart) {
        headerLines.push(`# Recording start: ${opts.recordingStart}`)
    }
    if (opts.filterSummary) {
        headerLines.push(`# Filter: ${opts.filterSummary}`)
    }
    headerLines.push(`# Items: ${sliced.length}${truncated ? ` (truncated from ${exportableCount})` : ''}`)
    const body = sliced.map(itemToText).join('\n\n')
    return { output: `${headerLines.join('\n')}\n\n${body}`, itemCount: sliced.length, truncated }
}
