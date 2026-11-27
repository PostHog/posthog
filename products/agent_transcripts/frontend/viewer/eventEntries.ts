import {
    blocksText,
    JsonRecord,
    parseJson,
    record,
    string,
    TranscriptEntry,
    TranscriptEntryKind,
    toolKind,
    toolText,
} from './transcriptEntries'

type EntryUpdate = Omit<TranscriptEntry, 'sequence'> & { sequence?: number }

const SHELL_TOOLS = /^(bash|shell|exec_command|command_execution|local_shell|terminal|run_terminal_cmd)$/i

// Codex sends its harness instructions as user messages. They are setup, not something the person typed.
const CODEX_SETUP_MESSAGE = /^\s*(<environment_context>|<user_instructions>|<permissions|# AGENTS\.md)/

function toolStatus(failed: boolean, done: boolean): TranscriptEntry['status'] {
    return failed ? 'failed' : done ? 'passed' : 'running'
}

/** Claude Code session files and stream-json, Cursor CLI and Pi: messages with content blocks. */
function messageEntries(event: JsonRecord, sequence: number): EntryUpdate[] {
    if (event.type === 'tool_execution_start' || event.type === 'tool_execution_end') {
        const name = string(event.toolName)
        return [
            {
                id: `tool-${String(event.toolCallId ?? sequence)}`,
                kind: toolKind(name),
                title: name,
                text: toolText(event.args),
                output: blocksText(record(event.result).content),
                status: toolStatus(!!event.isError, event.type === 'tool_execution_end'),
            },
        ]
    }

    if (!['message_end', 'assistant', 'user'].includes(String(event.type))) {
        return []
    }
    const message = record(event.message)
    if (message.role === 'toolResult') {
        return []
    }

    const content = Array.isArray(message.content) ? message.content : [{ type: 'text', text: message.content }]
    // Claude Code writes one line per content block, so blocks of one message share its ID. The line's own ID keeps them apart.
    const messageId = String(event.uuid ?? message.id ?? sequence)
    const fromUser = message.role === 'user' || event.type === 'user'

    return content.flatMap((raw, index): EntryUpdate[] => {
        const block = record(raw)
        const id = `message-${messageId}-${String(block.type)}-${index}`

        if (block.type === 'tool_use') {
            const name = string(block.name)
            return [
                {
                    id: `tool-${String(block.id)}`,
                    kind: toolKind(name),
                    title: name,
                    text: toolText(block.input),
                    status: 'running',
                },
            ]
        }
        if (block.type === 'tool_result') {
            return [
                {
                    id: `tool-${String(block.tool_use_id)}`,
                    kind: 'tool',
                    title: '',
                    text: '',
                    output: blocksText(block.content),
                    status: block.is_error ? 'failed' : 'passed',
                },
            ]
        }
        if (block.type === 'thinking' && string(block.thinking)) {
            return [{ id, kind: 'thinking', title: '', text: string(block.thinking) }]
        }
        if (block.type === 'text' && string(block.text)) {
            return [
                {
                    id,
                    kind: event.isMeta ? 'system' : fromUser ? 'user' : 'message',
                    title: '',
                    text: string(block.text),
                },
            ]
        }
        return []
    })
}

function codexOutput(raw: unknown): { output: string; exitCode?: number } {
    const text = string(raw) || blocksText(raw)
    // Older Codex versions wrap a shell result as JSON with its exit code in `metadata`.
    const wrapped = record(parseJson(text))
    if (typeof wrapped.output === 'string') {
        const exitCode = record(wrapped.metadata).exit_code
        return { output: wrapped.output, ...(typeof exitCode === 'number' && { exitCode }) }
    }
    const exitCode = /^Exit code: (\d+)/.exec(text)?.[1]
    return { output: text, ...(exitCode !== undefined && { exitCode: Number(exitCode) }) }
}

/** Codex session files (`~/.codex/sessions/**.jsonl`), where each line wraps an item in `payload`. */
function codexRolloutEntries(event: JsonRecord, sequence: number): EntryUpdate[] {
    if (event.type !== 'response_item') {
        return []
    }
    const item = record(event.payload)
    const id = `codex-${sequence}`

    switch (item.type) {
        case 'message': {
            const text = blocksText(item.content)
            if (!text || item.role === 'developer' || item.role === 'system') {
                return []
            }
            const kind: TranscriptEntryKind =
                item.role === 'user' ? (CODEX_SETUP_MESSAGE.test(text) ? 'system' : 'user') : 'message'
            return [{ id, kind, title: kind === 'system' ? 'Context' : '', text }]
        }
        case 'reasoning': {
            const text = blocksText(item.summary)
            return text ? [{ id, kind: 'thinking', title: '', text }] : []
        }
        case 'function_call':
        case 'custom_tool_call': {
            const name = string(item.name)
            const args = item.type === 'function_call' ? parseJson(string(item.arguments)) : undefined
            const input = string(item.input)
            return [
                {
                    id: `tool-${String(item.call_id)}`,
                    kind: toolKind(name),
                    title: name,
                    // A custom tool's input is free text, such as a whole patch.
                    text: args !== undefined ? toolText(args) : input,
                    status: 'running',
                },
            ]
        }
        case 'local_shell_call':
            return [
                {
                    id: `tool-${String(item.call_id)}`,
                    kind: 'tool',
                    title: 'shell',
                    text: toolText(record(item.action)),
                    status: toolStatus(item.status === 'failed', item.status === 'completed'),
                },
            ]
        case 'function_call_output':
        case 'custom_tool_call_output': {
            const { output, exitCode } = codexOutput(item.output)
            return [
                {
                    id: `tool-${String(item.call_id)}`,
                    kind: 'tool',
                    title: '',
                    text: '',
                    output,
                    ...(exitCode !== undefined && { exitCode }),
                    status: toolStatus(exitCode !== undefined && exitCode !== 0, true),
                },
            ]
        }
        case 'web_search_call':
            return [{ id, kind: 'web', title: 'web search', text: toolText(record(item.action)), status: 'passed' }]
        default:
            return []
    }
}

/** Codex `exec --json`, OpenCode and Cursor CLI tool events, which carry one item or part per line. */
function nativeEntries(event: JsonRecord, sequence: number): EntryUpdate[] {
    const item = record(event.item)
    const part = record(event.part)
    const id = `native-${String(item.id ?? part.id ?? sequence)}`

    if (item.type === 'agent_message' || item.type === 'reasoning') {
        return [{ id, kind: item.type === 'reasoning' ? 'thinking' : 'message', title: '', text: string(item.text) }]
    }

    if (['command_execution', 'file_change', 'mcp_tool_call', 'web_search'].includes(String(item.type))) {
        const shell = item.type === 'command_execution'
        return [
            {
                id,
                kind: toolKind(String(item.type)),
                title: shell ? 'shell' : String(item.tool ?? item.type).replaceAll('_', ' '),
                text:
                    string(item.command ?? item.query) ||
                    (item.changes ? JSON.stringify(item.changes) : toolText(item.arguments)),
                output:
                    string(item.aggregated_output) ||
                    blocksText(record(item.result).content) ||
                    string(record(item.error).message),
                ...(typeof item.exit_code === 'number' && { exitCode: item.exit_code }),
                status: toolStatus(
                    item.status === 'failed' || (typeof item.exit_code === 'number' && item.exit_code !== 0),
                    event.type === 'item.completed'
                ),
            },
        ]
    }

    if (event.type === 'text' || event.type === 'reasoning') {
        return [{ id, kind: event.type === 'reasoning' ? 'thinking' : 'message', title: '', text: string(part.text) }]
    }

    if (event.type === 'tool_use' || part.type === 'tool') {
        const state = record(part.state)
        const name = string(part.tool) || 'tool'
        return [
            {
                id: `tool-${String(part.callID ?? part.id ?? sequence)}`,
                kind: toolKind(name),
                title: name,
                text: toolText(state.input) || string(state.title),
                output: string(state.output ?? state.error),
                status: toolStatus(state.status === 'error', state.status === 'completed'),
            },
        ]
    }

    if (event.type === 'tool_call') {
        // Cursor names the call by its key, for example `{ shellToolCall: { args, result } }`.
        const [key, raw] = Object.entries(record(event.tool_call))[0] ?? ['tool', {}]
        const call = record(raw)
        const result = record(call.result)
        const success = record(result.success)
        const failure = result.error ?? result.failure
        return [
            {
                id: `tool-${String(event.call_id ?? sequence)}`,
                kind: toolKind(key),
                title: key.replace(/ToolCall$/, ''),
                text: toolText(call.args),
                output:
                    string(success.stdout) ||
                    string(success.content) ||
                    (Object.keys(success).length ? JSON.stringify(success) : '') ||
                    string(record(failure).message) ||
                    string(failure),
                ...(typeof success.exitCode === 'number' && { exitCode: success.exitCode }),
                status: toolStatus(!!failure, event.subtype === 'completed'),
            },
        ]
    }

    if (event.type === 'error' || event.type === 'turn.failed') {
        return [
            {
                id,
                kind: 'system',
                title: 'Error',
                text: string(record(event.error).message) || string(event.error) || 'The agent failed.',
                status: 'failed',
            },
        ]
    }

    return []
}

/**
 * Entries from a list of agent events, one per JSONL line. Updates to the same ID merge into one row,
 * so a tool result joins its call and keeps the call's position.
 */
export function eventEntries(events: unknown[]): TranscriptEntry[] {
    const entries = new Map<string, TranscriptEntry>()

    events.forEach((raw, index) => {
        const event = record(raw)
        const sequence = index + 1
        const updates = [
            ...messageEntries(event, sequence),
            ...codexRolloutEntries(event, sequence),
            ...nativeEntries(event, sequence),
        ]

        for (const update of updates) {
            const previous = entries.get(update.id)
            entries.set(update.id, {
                ...previous,
                ...update,
                sequence: previous?.sequence ?? sequence,
                title: update.title || previous?.title || '',
                text: update.text || previous?.text || '',
                kind: previous?.kind ?? update.kind,
                output: update.output || previous?.output || '',
            })
        }

        const result = string(event.result)
        if (event.type === 'result' && result && ![...entries.values()].some((entry) => entry.text === result)) {
            entries.set(`result-${sequence}`, {
                id: `result-${sequence}`,
                sequence,
                kind: event.is_error ? 'system' : 'message',
                title: event.is_error ? 'Error' : '',
                text: result,
            })
        }
    })

    return [...entries.values()]
}

export const isShellTool = (entry: TranscriptEntry): boolean => SHELL_TOOLS.test(entry.title)
