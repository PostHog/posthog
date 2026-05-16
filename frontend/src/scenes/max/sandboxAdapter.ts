// Convert sandbox ACP log entries into the standard ThreadMessage shape so they
// can flow through the same rendering paths as LangGraph messages.
//
// The PostHog sandbox stream emits ACP `session/update` notifications which are
// parsed into LogEntry rows by products/tasks/frontend/lib/parse-logs. This
// adapter takes those entries and produces ThreadMessage records matching the
// pydantic schemas (HumanMessage / AssistantMessage / ReasoningMessage /
// AssistantToolCallMessage) that the LangGraph path persists to
// Conversation.messages_json.
//
// Use this when replaying a session log on conversation reload, and when
// mirroring the live stream into threadRaw for sandbox-mode conversations
// (so the standard <Message> renderer can take over from SandboxSessionView).

import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCall,
    AssistantToolCallMessage,
    ReasoningMessage,
} from '~/queries/schema/schema-assistant-messages'

import { LogEntry } from 'products/tasks/frontend/lib/parse-logs'

import type { ThreadMessage } from './maxThreadLogic'

export interface AdapterAssistantToolCallMessage extends Omit<AssistantToolCallMessage, 'ui_payload'> {
    ui_payload: {
        // Mirrors the ``_sandbox: True`` marker the backend writes (see
        // ee/hogai/sandbox/turn_builder.py) so renderers can tell sandbox MCP
        // tool calls apart from LangGraph contextual-tool ui_payloads.
        _sandbox: true
        name: string
        status?: string
        args?: Record<string, unknown>
        output?: unknown
    }
}

type AdapterOutput = AssistantMessage | ReasoningMessage | AdapterAssistantToolCallMessage | null

/**
 * Convert a single LogEntry into a ThreadMessage-shaped record.
 *
 * Returns `null` for entry types that don't surface as a chat message
 * (`console`, `system`, `raw`, `user` setup-logs). Streaming text and tool
 * call updates are accumulated by the caller — this function returns one
 * snapshot per LogEntry, mirroring the per-event granularity of the live
 * sandbox stream.
 */
export function logEntryToThreadMessage(entry: LogEntry): AdapterOutput {
    switch (entry.type) {
        case 'agent':
            return {
                type: AssistantMessageType.Assistant,
                id: `sandbox-${entry.id}`,
                content: entry.message ?? '',
            }
        case 'thinking':
            return {
                type: AssistantMessageType.Reasoning,
                id: `sandbox-thinking-${entry.id}`,
                content: entry.message ?? '',
            }
        case 'tool': {
            if (!entry.toolCallId) {
                return null
            }
            const toolCallMessage: AdapterAssistantToolCallMessage = {
                type: AssistantMessageType.ToolCall,
                id: `sandbox-tool-${entry.toolCallId}`,
                tool_call_id: entry.toolCallId,
                content: typeof entry.toolResult === 'string' ? entry.toolResult : (entry.message ?? ''),
                ui_payload: {
                    _sandbox: true,
                    name: entry.toolName || 'unknown_tool',
                    status: entry.toolStatus,
                    args: entry.toolArgs,
                    output: entry.toolResult,
                },
            }
            return toolCallMessage
        }
        default:
            // 'console' | 'system' | 'raw' | 'user' — not surfaced in the thread
            return null
    }
}

/**
 * Build the `tool_calls` array on an AssistantMessage from the tool entries
 * that were emitted since the last assistant text flush.
 *
 * Mirrors the backend SandboxTurnBuilder behavior so a reload-from-server and
 * a live stream produce the same final message shape.
 */
export function attachToolCallsToAssistantMessage(
    assistantMessage: AssistantMessage,
    toolEntries: LogEntry[]
): AssistantMessage {
    const toolCalls: AssistantToolCall[] = toolEntries
        .filter((entry) => entry.type === 'tool' && entry.toolCallId)
        .map((entry) => ({
            id: entry.toolCallId as string,
            name: entry.toolName || 'unknown_tool',
            args: (entry.toolArgs as Record<string, unknown>) || {},
            type: 'tool_call' as const,
        }))
    if (toolCalls.length === 0) {
        return assistantMessage
    }
    return { ...assistantMessage, tool_calls: toolCalls }
}

/**
 * Convert an ordered list of LogEntry rows (e.g. from a session_logs replay)
 * into a flat list of ThreadMessage-compatible records. Adjacent `agent`
 * entries are coalesced into a single `AssistantMessage`, mirroring how
 * `SandboxSessionView.classifySandboxEntries` does it for inline rendering.
 */
export function logEntriesToThreadMessages(entries: LogEntry[]): AdapterOutput[] {
    const out: AdapterOutput[] = []
    let pendingText: { id: string; text: string } | null = null
    let pendingThinking: { id: string; text: string } | null = null

    const flushText = (): void => {
        if (pendingText) {
            out.push({
                type: AssistantMessageType.Assistant,
                id: `sandbox-${pendingText.id}`,
                content: pendingText.text,
            })
            pendingText = null
        }
    }
    const flushThinking = (): void => {
        if (pendingThinking) {
            out.push({
                type: AssistantMessageType.Reasoning,
                id: `sandbox-thinking-${pendingThinking.id}`,
                content: pendingThinking.text,
            })
            pendingThinking = null
        }
    }

    for (const entry of entries) {
        if (entry.type === 'agent') {
            flushThinking()
            if (pendingText) {
                pendingText.text += entry.message ?? ''
            } else {
                pendingText = { id: entry.id, text: entry.message ?? '' }
            }
            continue
        }
        if (entry.type === 'thinking') {
            flushText()
            if (pendingThinking) {
                pendingThinking.text += entry.message ?? ''
            } else {
                pendingThinking = { id: entry.id, text: entry.message ?? '' }
            }
            continue
        }
        if (entry.type === 'tool') {
            flushText()
            flushThinking()
            const adapted = logEntryToThreadMessage(entry)
            if (adapted) {
                out.push(adapted)
            }
            continue
        }
        // console / system / raw / user — skip
    }
    flushText()
    flushThinking()
    return out
}

/**
 * Helper for callers that already keep ThreadMessage[] as their state. Returns
 * the adapter output as ThreadMessage-compatible records with default status.
 */
export function asThreadMessages(adapted: AdapterOutput[]): ThreadMessage[] {
    return adapted
        .filter((m): m is NonNullable<AdapterOutput> => m !== null)
        .map((m) => ({ ...m, status: 'completed' as const }))
}
