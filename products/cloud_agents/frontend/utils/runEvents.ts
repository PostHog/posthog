import type { CloudAgentRunEventsApiEventsItem } from '../generated/api.schemas'

export type TimelineRowKind = 'assistant' | 'user' | 'tool' | 'status' | 'unknown'

export interface TimelineRow {
    key: string
    kind: TimelineRowKind
    /** A short label: the tool name, the status, or the name of an event that has no renderer. */
    title: string
    /** The message text, or a one-line summary of a tool call. */
    body: string | null
    timestamp: string | null
    /** For a tool row: the latest status that the agent reported for the call. */
    status?: string | null
}

type Json = Record<string, unknown>

const SUMMARY_MAX_LENGTH = 160

function asObject(value: unknown): Json | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : null
}

function asString(value: unknown): string | null {
    return typeof value === 'string' && value.length > 0 ? value : null
}

function truncate(text: string): string {
    const singleLine = text.replace(/\s+/g, ' ').trim()
    return singleLine.length > SUMMARY_MAX_LENGTH ? `${singleLine.slice(0, SUMMARY_MAX_LENGTH - 1)}…` : singleLine
}

/** The text of a content block, or of a list of them. Blocks that are not text add nothing. */
function contentText(content: unknown): string | null {
    if (typeof content === 'string') {
        return content || null
    }
    if (Array.isArray(content)) {
        const parts = content.map(contentText).filter((part): part is string => !!part)
        return parts.length > 0 ? parts.join('') : null
    }
    const block = asObject(content)
    if (!block) {
        return null
    }
    return asString(block.text) ?? contentText(block.content)
}

function toolSummary(update: Json): string | null {
    const input = asObject(update.rawInput)
    if (input) {
        const value =
            asString(input.command) ?? asString(input.file_path) ?? asString(input.path) ?? asString(input.pattern)
        if (value) {
            return truncate(value)
        }
        const json = JSON.stringify(input)
        return json === '{}' ? null : truncate(json)
    }
    return null
}

function humanize(name: string): string {
    const words = name
        .replace(/^_?posthog\//, '')
        .replace(/[_/.-]+/g, ' ')
        .trim()
    return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Event'
}

/**
 * Turns the stored agent protocol frames into rows for the timeline.
 *
 * The frames come from the agent runtime, and their shape can change without a change here. So every
 * read checks the type first, and a frame that matches no branch becomes an `unknown` row and never throws.
 * Message chunks that follow each other merge into one row, and a tool call update changes the row of its call.
 */
export function buildTimeline(events: CloudAgentRunEventsApiEventsItem[]): TimelineRow[] {
    const rows: TimelineRow[] = []
    const toolRows = new Map<string, TimelineRow>()

    const appendText = (kind: 'assistant' | 'user', title: string, text: string, timestamp: string | null): void => {
        const last = rows[rows.length - 1]
        if (last && last.kind === kind && last.title === title) {
            last.body = (last.body ?? '') + text
            return
        }
        rows.push({ key: `${rows.length}`, kind, title, body: text, timestamp })
    }

    for (const event of Array.isArray(events) ? events : []) {
        const frame = asObject(event)
        if (!frame) {
            rows.push({ key: `${rows.length}`, kind: 'unknown', title: 'Event', body: null, timestamp: null })
            continue
        }
        const timestamp = asString(frame.timestamp)
        const message = asObject(frame.notification) ?? frame
        const method = asString(message.method)
        const params = asObject(message.params)
        const update = asObject(params?.update)
        const updateType = asString(update?.sessionUpdate)

        if (update && updateType === 'agent_message_chunk') {
            const text = contentText(update.content)
            if (text) {
                appendText('assistant', 'Agent', text, timestamp)
            }
            continue
        }
        if (update && updateType === 'user_message_chunk') {
            const text = contentText(update.content)
            if (text) {
                appendText('user', 'You', text, timestamp)
            }
            continue
        }
        if (update && updateType === 'agent_thought_chunk') {
            // The reasoning of the agent is long and changes with each chunk, so the timeline leaves it out.
            continue
        }
        if (update && (updateType === 'tool_call' || updateType === 'tool_call_update')) {
            const toolCallId = asString(update.toolCallId)
            const existing = toolCallId ? toolRows.get(toolCallId) : undefined
            const title = asString(update.title) ?? asString(update.kind)
            const summary = toolSummary(update)
            const status = asString(update.status)
            if (existing) {
                existing.title = title ?? existing.title
                existing.body = summary ?? existing.body
                existing.status = status ?? existing.status
                continue
            }
            const row: TimelineRow = {
                key: `${rows.length}`,
                kind: 'tool',
                title: title ?? 'Tool call',
                body: summary,
                timestamp,
                status,
            }
            rows.push(row)
            if (toolCallId) {
                toolRows.set(toolCallId, row)
            }
            continue
        }
        if (method === 'session/prompt') {
            const text = contentText(params?.prompt)
            if (text) {
                appendText('user', 'You', text, timestamp)
                continue
            }
        }
        if (method && method.startsWith('_posthog/')) {
            const text = asString(params?.message) ?? asString(params?.status) ?? asString(params?.error)
            rows.push({
                key: `${rows.length}`,
                kind: 'status',
                title: humanize(method),
                body: text ? truncate(text) : null,
                timestamp,
            })
            continue
        }
        rows.push({
            key: `${rows.length}`,
            kind: 'unknown',
            title: humanize(updateType ?? method ?? asString(frame.type) ?? 'Event'),
            body: null,
            timestamp,
        })
    }
    return rows
}
