import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import {
    mapHttpStatusToStreamError,
    MAX_CUMULATIVE_RECONNECT_ATTEMPTS,
    MAX_SSE_RECONNECT_ATTEMPTS,
    parsePermissionRequestFrame,
    reconnectDelayMs,
    resolveToolKey,
    sandboxStreamLogic,
    SSE_HEALTHY_CONNECTION_MS,
    SSE_RECONNECT_BASE_DELAY_MS,
    SSE_RECONNECT_MAX_DELAY_MS,
} from './sandboxStreamLogic'
import type { PermissionRequestFrame, StoredLogEntry } from './types/sandboxWireTypes'

function notification(method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', notification: { method, params } }
}

function sessionUpdate(update: Record<string, unknown>): StoredLogEntry {
    return notification('session/update', { update })
}

/** Minimal `EventSource` stand-in so the logic can open/drop a connection under test control. */
class MockEventSource {
    static instances: MockEventSource[] = []
    url: string
    onopen: (() => void) | null = null
    onmessage: ((event: MessageEvent<string>) => void) | null = null
    closed = false
    private errorListeners: ((event: MessageEvent<string>) => void)[] = []

    constructor(url: string) {
        this.url = url
        MockEventSource.instances.push(this)
    }

    addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
        if (type === 'error') {
            this.errorListeners.push(listener)
        }
    }

    close(): void {
        this.closed = true
    }

    emitOpen(): void {
        this.onopen?.()
    }

    /** Simulate a default-channel `event: message` data frame. */
    emitMessage(data: Record<string, unknown>): void {
        this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>)
    }

    /** Simulate a transient connection drop (no `data`). */
    emitDrop(): void {
        this.errorListeners.forEach((l) => l({ data: '' } as MessageEvent<string>))
    }

    /** Simulate a named `event: error` envelope frame. */
    emitErrorFrame(envelope: Record<string, unknown>): void {
        this.errorListeners.forEach((l) => l({ data: JSON.stringify(envelope) } as MessageEvent<string>))
    }

    static latest(): MockEventSource {
        return MockEventSource.instances[MockEventSource.instances.length - 1]
    }

    static reset(): void {
        MockEventSource.instances = []
    }
}

describe('sandboxStreamLogic', () => {
    let logic: ReturnType<typeof sandboxStreamLogic.build>

    beforeEach(() => {
        initKeaTests()
        MockEventSource.reset()
        ;(global as any).EventSource = MockEventSource
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess({ id: 997 } as any)
        logic = sandboxStreamLogic({ conversationId: 'test-conversation' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    describe('resolveToolKey', () => {
        it('parses the inner tool name out of a single-exec call command', () => {
            const resolved = resolveToolKey('posthog', 'exec', { command: 'call insight-create {"name":"Signups"}' })
            expect(resolved.resolvedKey).toEqual('insight-create')
            expect(resolved.innerToolName).toEqual('insight-create')
            expect(resolved.innerInput).toEqual({ name: 'Signups' })
        })

        it('maps discovery verbs to sentinels', () => {
            expect(resolveToolKey('posthog', 'exec', { command: 'tools' }).resolvedKey).toEqual(
                '__posthog_exec_tools__'
            )
            expect(resolveToolKey('posthog', 'exec', { command: 'search recordings' }).resolvedKey).toEqual(
                '__posthog_exec_search__'
            )
        })

        it('falls back to unknown sentinel for malformed commands', () => {
            expect(resolveToolKey('posthog', 'exec', { command: '!!!' }).resolvedKey).toEqual(
                '__posthog_exec_unknown__'
            )
        })

        it('returns the wire name for non-exec MCP tools that carry one', () => {
            expect(resolveToolKey('user-mcp', 'do_thing', {}).resolvedKey).toEqual('do_thing')
        })

        it.each(['Edit', 'TodoWrite', 'Grep', 'Task'])(
            'falls back to the SDK %s name when the wire toolName is empty (every Claude built-in)',
            (sdkName) => {
                // Built-ins carry no top-level toolName on the wire — only `_meta.claudeCode.toolName`.
                expect(resolveToolKey('claude', '', {}, sdkName).resolvedKey).toEqual(sdkName)
            }
        )

        it('prefers the explicit wire toolName over the SDK name when both are present', () => {
            expect(resolveToolKey('user-mcp', 'do_thing', {}, 'Edit').resolvedKey).toEqual('do_thing')
        })

        it('resolves to empty string when neither a wire toolName nor an SDK name is present', () => {
            expect(resolveToolKey('claude', '', {}).resolvedKey).toEqual('')
        })
    })

    describe('ingestAcpFrame replay', () => {
        it('folds a stream of StoredLogEntry frames into thread items', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/run_started', {}),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'Hel' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'lo' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hello' } }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    status: 'completed',
                    rawOutput: { rows: 1 },
                    content: [{ type: 'text', text: 'done' }],
                }),
                notification('_posthog/turn_complete', {}),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.runStarted).toEqual(true)
            expect(logic.values.turnComplete).toEqual(true)

            const assistantItem = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistantItem?.text).toEqual('Hello')
            expect(assistantItem?.complete).toEqual(true)

            const toolItem = logic.values.threadItems.find((item) => item.type === 'tool_invocation')
            expect(toolItem?.toolCallId).toEqual('t1')

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.resolvedKey).toEqual('execute-sql')
            expect(invocation?.status).toEqual('completed')
            expect(invocation?.output).toEqual({ rows: 1 })
            expect(invocation?.contentBlocks).toEqual([{ type: 'text', text: 'done' }])

            expect(logic.values.threadItems.some((item) => item.type === 'turn_separator')).toEqual(true)
        })

        it('sets currentMode on a current_mode_update frame', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'current_mode_update', currentModeId: 'plan' })
                )
            }).toFinishAllListeners()

            expect(logic.values.currentMode).toEqual('plan')
        })

        it('sets currentProgress on a _posthog/progress frame and clears it on turn complete', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/progress', { label: 'Querying events' }))
            }).toFinishAllListeners()

            expect(logic.values.currentProgress).toEqual('Querying events')

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            }).toFinishAllListeners()

            expect(logic.values.currentProgress).toBeNull()
        })

        it('drives terminal status off handleTerminalStatus', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'completed' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('completed')
        })
    })

    describe('assistant message buffering without messageId', () => {
        it('keeps two consecutive turns without a messageId in separate thread items', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'One' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'One' } }),
                notification('_posthog/turn_complete', {}),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Tw' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'o' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', content: { text: 'Two' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(2)
            expect(assistantItems[0].text).toEqual('One')
            expect(assistantItems[0].complete).toEqual(true)
            expect(assistantItems[1].text).toEqual('Two')
            expect(assistantItems[1].complete).toEqual(true)
            expect(assistantItems[0].id).not.toEqual(assistantItems[1].id)
        })

        it('keeps text before and after a tool call as separate items in wire order', async () => {
            // Real wire pattern: streamed text, a tool call, then more streamed text — all in one
            // turn with no agent_message finalize between them and no messageId on any chunk.
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Let me ' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'check.' } }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'All ' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'set.' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.threadItems.map((item) => item.type)).toEqual([
                'assistant_message',
                'tool_invocation',
                'assistant_message',
            ])
            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems[0].text).toEqual('Let me check.')
            expect(assistantItems[1].text).toEqual('All set.')
            expect(assistantItems[0].id).not.toEqual(assistantItems[1].id)
        })

        it('starts a new bubble for a chunk arriving after finalize instead of mutating the finalized one', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'Done' } }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Done' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'More' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(2)
            expect(assistantItems[0].text).toEqual('Done')
            expect(assistantItems[0].complete).toEqual(true)
            expect(assistantItems[1].text).toEqual('More')
            expect(assistantItems[1].complete).toEqual(false)
            expect(assistantItems[0].id).not.toEqual(assistantItems[1].id)
        })
    })

    describe('agent thought buffering', () => {
        it('folds consecutive thought chunks into one assistant_thought item', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Let me ' } }),
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'think.' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const thoughtItems = logic.values.threadItems.filter((item) => item.type === 'assistant_thought')
            expect(thoughtItems).toHaveLength(1)
            expect(thoughtItems[0].text).toEqual('Let me think.')
        })

        it('keeps thoughts, messages, and tool calls as separate items in wire order', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Checking the data' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Let me look.' } }),
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Now I know.' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.threadItems.map((item) => item.type)).toEqual([
                'assistant_thought',
                'assistant_message',
                'tool_invocation',
                'assistant_thought',
            ])
            const thoughtItems = logic.values.threadItems.filter((item) => item.type === 'assistant_thought')
            expect(thoughtItems[0].text).toEqual('Checking the data')
            expect(thoughtItems[1].text).toEqual('Now I know.')
            expect(thoughtItems[0].id).not.toEqual(thoughtItems[1].id)
        })

        it('does not collide thought and message buffers that share the fallback id', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({ sessionUpdate: 'agent_thought_chunk', content: { text: 'Thinking' } }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { text: 'Answer' } }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const thought = logic.values.threadItems.find((item) => item.type === 'assistant_thought')
            const message = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(thought?.text).toEqual('Thinking')
            expect(message?.text).toEqual('Answer')
            expect(thought?.id).not.toEqual(message?.id)
        })
    })

    describe('streamed tool input', () => {
        it('folds rawInput arriving on a later update into a built-in tool call keyed off _meta', async () => {
            // Built-ins carry no top-level toolName — the SDK name arrives only on `_meta.claudeCode`.
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    title: 'ToolSearch',
                    rawInput: {},
                    status: 'pending',
                    _meta: { claudeCode: { toolName: 'ToolSearch' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    rawInput: { query: 'find recordings', max_results: 10 },
                    status: 'completed',
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.input).toEqual({ query: 'find recordings', max_results: 10 })
            expect(invocation?.resolvedKey).toEqual('ToolSearch')
            expect(invocation?.claudeToolName).toEqual('ToolSearch')
        })

        it('re-resolves the registry key when an exec command streams in after an empty tool_call', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't2',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: {},
                    status: 'pending',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't2',
                    rawInput: { command: 'call insight-create {"name":"Signups"}' },
                    status: 'in_progress',
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t2')
            expect(invocation?.resolvedKey).toEqual('insight-create')
            expect(invocation?.innerToolName).toEqual('insight-create')
            expect(invocation?.innerInput).toEqual({ name: 'Signups' })
        })

        it.each(['Edit', 'TodoWrite', 'Grep', 'Task'])(
            'keys a built-in %s tool_call off _meta.claudeCode.toolName despite an empty wire toolName',
            async (sdkName) => {
                const frames: StoredLogEntry[] = [
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 'tb',
                        title: `${sdkName} \`foo.ts\``,
                        rawInput: {},
                        status: 'in_progress',
                        _meta: { claudeCode: { toolName: sdkName } },
                    }),
                ]

                await expectLogic(logic, () => {
                    frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
                }).toFinishAllListeners()

                const invocation = logic.values.toolInvocations.get('tb')
                expect(invocation?.resolvedKey).toEqual(sdkName)
                expect(invocation?.claudeToolName).toEqual(sdkName)
            }
        )

        it('keeps the resolved input when a later update carries none', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't3',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't3',
                    status: 'completed',
                    rawOutput: { rows: 1 },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t3')
            expect(invocation?.resolvedKey).toEqual('execute-sql')
            expect(invocation?.innerInput).toEqual({ query: 'select 1' })
        })
    })

    describe('pushHumanMessage', () => {
        it('appends a human_message item ordered before subsequently ingested assistant frames', async () => {
            await expectLogic(logic, () => {
                logic.actions.pushHumanMessage('hello agent')
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hi!' } })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(2)
            expect(logic.values.threadItems[0]).toEqual({
                id: 'human-0',
                type: 'human_message',
                text: 'hello agent',
                complete: true,
            })
            expect(logic.values.threadItems[1].type).toEqual('assistant_message')
        })
    })

    describe('_posthog/user_message rendering', () => {
        it('renders a seeded user turn into the thread on bootstrap replay', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/user_message', { content: 'Why did checkout drop?' }),
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Let me check.' } }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            // Both the human question and the assistant reply must render, in order.
            expect(logic.values.threadItems).toHaveLength(2)
            expect(logic.values.threadItems[0]).toEqual({
                id: 'human-0',
                type: 'human_message',
                text: 'Why did checkout drop?',
                complete: true,
            })
            expect(logic.values.threadItems[1].type).toEqual('assistant_message')
        })

        it('extracts text from ACP content blocks', async () => {
            const frames: StoredLogEntry[] = [
                notification('_posthog/user_message', {
                    content: [
                        { type: 'text', text: 'first ' },
                        { type: 'text', text: 'second' },
                    ],
                }),
            ]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(1)
            expect(logic.values.threadItems[0]).toMatchObject({ type: 'human_message', text: 'first second' })
        })

        it('strips the posthog_context wrapper so a replayed prompt matches the live one', async () => {
            const wrapped =
                '<posthog_context>\nThe user attached the following PostHog entities.\n- Insight #1\n</posthog_context>\n\nWhy did signups drop?'
            const frames: StoredLogEntry[] = [notification('_posthog/user_message', { content: wrapped })]
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue(frames as any)
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            await expectLogic(logic, () => {
                logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.find((item) => item.type === 'human_message')?.text).toEqual(
                'Why did signups drop?'
            )
        })

        it('does not render a live (non-replay) user_message frame — it is echoed on send instead', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/user_message', { content: 'live message' }))
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(0)
        })
    })

    describe('per-conversation isolation', () => {
        it('keeps thread state independent between two mounted conversations', async () => {
            const otherLogic = sandboxStreamLogic({ conversationId: 'other-conversation' })
            otherLogic.mount()

            await expectLogic(logic, () => {
                logic.actions.pushHumanMessage('hello agent')
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hi!' } })
                )
            }).toFinishAllListeners()

            expect(logic.values.threadItems).toHaveLength(2)
            expect(otherLogic.values.threadItems).toHaveLength(0)

            otherLogic.unmount()
        })
    })

    describe('tool call errors', () => {
        it('populates error from a failed tool_call_update carrying an error message', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't1',
                    status: 'failed',
                    error: { message: 'command exploded' },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t1')
            expect(invocation?.status).toEqual('failed')
            expect(invocation?.error?.message).toEqual('command exploded')
        })

        it('falls back to the notification-level error when a failed update has none', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't2',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'tools' },
                    status: 'in_progress',
                }),
                {
                    type: 'notification',
                    notification: {
                        method: 'session/update',
                        params: { update: { sessionUpdate: 'tool_call_update', toolCallId: 't2', status: 'failed' } },
                        error: { message: 'sandbox crashed' },
                    },
                },
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            expect(logic.values.toolInvocations.get('t2')?.error?.message).toEqual('sandbox crashed')
        })

        it('surfaces the _meta.claudeCode denial reason on a failed update with no explicit error', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't3',
                    title: 'Edit `foo.ts`',
                    rawInput: {},
                    status: 'in_progress',
                    _meta: { claudeCode: { toolName: 'Edit' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't3',
                    status: 'failed',
                    content: [
                        { type: 'content', content: { type: 'text', text: 'Permission denied: writes blocked' } },
                    ],
                    _meta: {
                        claudeCode: {
                            toolName: 'Edit',
                            toolResponse: {
                                decisionReason: 'Edits are not allowed in read-only mode',
                                decisionReasonType: 'policy',
                                message: 'denied',
                            },
                        },
                    },
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t3')
            expect(invocation?.status).toEqual('failed')
            expect(invocation?.error?.message).toEqual('Edits are not allowed in read-only mode')
        })

        it('upserts a renderable invocation from a terminal update whose tool_call frame was lost', async () => {
            // A reconnect with ?start=latest can drop the creating frame; the terminal update must
            // still render a card, and must not fire completion telemetry with an undefined name.
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 'orphan', status: 'completed' })
                )
            }).toFinishAllListeners()

            expect(logic.values.toolInvocations.get('orphan')?.status).toEqual('completed')
            expect(logic.values.threadItems.some((item) => item.toolCallId === 'orphan')).toEqual(true)
            expect(captureSpy.mock.calls.filter((c) => c[0] === 'tool_call_completed')).toHaveLength(0)
        })

        it('does not throw and keeps no error on the inline-denial path (failed, no _meta)', async () => {
            const frames: StoredLogEntry[] = [
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't4',
                    title: 'Bash `rm -rf`',
                    rawInput: {},
                    status: 'in_progress',
                    _meta: { claudeCode: { toolName: 'Bash' } },
                }),
                sessionUpdate({
                    sessionUpdate: 'tool_call_update',
                    toolCallId: 't4',
                    status: 'failed',
                    content: [
                        { type: 'content', content: { type: 'text', text: 'User refused permission to run Bash' } },
                    ],
                }),
            ]

            await expectLogic(logic, () => {
                frames.forEach((frame) => logic.actions.ingestAcpFrame(frame))
            }).toFinishAllListeners()

            const invocation = logic.values.toolInvocations.get('t4')
            expect(invocation?.status).toEqual('failed')
            // No _meta and no explicit error → the renderer falls back to the content text; no error.message synthesized.
            expect(invocation?.error?.message).toBeUndefined()
            expect(invocation?.contentBlocks).toHaveLength(1)
        })
    })

    describe('content dedup', () => {
        it('folds an entry once and drops an identical replay', async () => {
            const frame = sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'Hi' } })

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(frame)
                logic.actions.ingestAcpFrame(frame)
            }).toFinishAllListeners()

            const assistantItems = logic.values.threadItems.filter((item) => item.type === 'assistant_message')
            expect(assistantItems).toHaveLength(1)
            expect(assistantItems[0].text).toEqual('Hi')
            expect(logic.cache.ingestedEntryHashes.size).toEqual(1)
        })

        it('does not dedup distinct chunks of the same message', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'A' } })
                )
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'agent_message_chunk', messageId: 'm1', content: { text: 'B' } })
                )
            }).toFinishAllListeners()

            const assistantItem = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistantItem?.text).toEqual('AB')
        })
    })

    describe('error mapping', () => {
        it('maps HTTP statuses to error envelopes', () => {
            expect(mapHttpStatusToStreamError(401)).toEqual({
                errorTitle: 'Cloud authentication expired',
                retryable: true,
            })
            expect(mapHttpStatusToStreamError(403)).toEqual({ errorTitle: 'Cloud access denied', retryable: true })
            expect(mapHttpStatusToStreamError(404)).toEqual({
                errorTitle: 'Conversation backing run not found',
                retryable: false,
            })
            expect(mapHttpStatusToStreamError(406)).toEqual({
                errorTitle: 'Cloud stream unavailable',
                retryable: true,
            })
            expect(mapHttpStatusToStreamError(500)).toEqual({ errorTitle: 'Cloud stream failed', retryable: true })
            expect(mapHttpStatusToStreamError(undefined)).toEqual({
                errorTitle: 'Cloud stream failed',
                retryable: true,
            })
        })

        it('caps the backoff schedule at 2s/4s/8s/16s/30s', () => {
            expect([1, 2, 3, 4, 5].map(reconnectDelayMs)).toEqual([2000, 4000, 8000, 16000, 30000])
            expect(reconnectDelayMs(6)).toEqual(SSE_RECONNECT_MAX_DELAY_MS)
        })

        it('surfaces a named event:error frame verbatim', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                MockEventSource.latest().emitErrorFrame({
                    errorTitle: 'Sandbox crashed',
                    errorMessage: 'boom',
                    retryable: false,
                })
            }).toMatchValues({ sseStatus: 'error' })
        })
    })

    describe('isThinking', () => {
        it('is on only while a started turn is incomplete, surviving non-terminal status updates', () => {
            expect(logic.values.isThinking).toEqual(false)

            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.isThinking).toEqual(true)

            logic.actions.handleTerminalStatus({ status: 'queued' })
            expect(logic.values.isThinking).toEqual(true)

            logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            expect(logic.values.isThinking).toEqual(false)
        })

        it.each([
            ['a terminal run status', (): void => logic.actions.handleTerminalStatus({ status: 'failed' })],
            ['a stream error', (): void => logic.actions.handleStreamError({ errorTitle: 'x', retryable: true })],
        ])('turns off on %s even when turn_complete never arrives', (_case, act) => {
            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.isThinking).toEqual(true)

            act()
            expect(logic.values.isThinking).toEqual(false)
        })

        it('re-raises on a follow-up turn opened by a human message, with no new run_started', () => {
            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            expect(logic.values.isThinking).toEqual(false)

            // A follow-up on the same run starts a new turn — no second run_started frame arrives.
            logic.actions.pushHumanMessage('and the mobile funnel?')
            expect(logic.values.isThinking).toEqual(true)
        })

        it('is on during the cold-boot queued window before the first run_started', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()

            // currentRunStatus is 'queued' and runStarted is still false — the indicator must show.
            expect(logic.values.currentRunStatus).toEqual('queued')
            expect(logic.values.isThinking).toEqual(true)
        })
    })

    describe('terminal-status handling', () => {
        it('closes the SSE and stops reconnects on a terminal task_run_state', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            const source = MockEventSource.latest()
            source.emitOpen()

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'completed' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('completed')
            expect(source.closed).toEqual(true)
        })

        it('keeps the stream open on a non-terminal task_run_state', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            const source = MockEventSource.latest()
            source.emitOpen()

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'in_progress' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('in_progress')
            expect(source.closed).toEqual(false)
        })
    })

    describe('reconnect / backoff', () => {
        it('refetches and surfaces terminal status on a drop, without reopening', async () => {
            const getSpy = jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            MockEventSource.latest().emitOpen()

            const beforeDrop = MockEventSource.instances.length
            logic.actions.sseDropped()
            await flushPromises()

            expect(getSpy).toHaveBeenCalledWith('task-1', 'run-1')
            expect(logic.values.currentRunStatus).toEqual('completed')
            // No new EventSource was created (terminal → no reconnect).
            expect(MockEventSource.instances.length).toEqual(beforeDrop)
        })

        it('backs off and reopens on a drop while the run is non-terminal', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            MockEventSource.latest().emitOpen()
            const beforeDrop = MockEventSource.instances.length

            jest.useFakeTimers()
            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('reconnecting')
            expect(logic.values.reconnectAttempt).toEqual(1)

            jest.advanceTimersByTime(2000)
            expect(MockEventSource.instances.length).toEqual(beforeDrop + 1)
            // The reconnect replays the full stream (no start=latest) so the content-dedup can
            // fill in frames emitted while disconnected instead of skipping past them.
            expect(MockEventSource.latest().url).not.toContain('start=latest')
            jest.useRealTimers()
        })

        it('preserves a known in-flight status when the reconnect reopens the stream', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.handleTerminalStatus({ status: 'in_progress' })
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1', startLatest: false })

            expect(logic.values.currentRunStatus).toEqual('in_progress')
        })

        it('abandons the drop loop when the stream is closed mid-refetch', async () => {
            let resolveGet: (value: unknown) => void = () => {}
            jest.spyOn(api.tasks.runs, 'get').mockReturnValue(new Promise((resolve) => (resolveGet = resolve)) as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.sseDropped()
            logic.actions.closeSse()

            resolveGet({ status: 'in_progress' })
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('closed')
            expect(logic.values.reconnectAttempt).toEqual(0)
        })

        it('surfaces a retryable error after exhausting the attempt cap', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            // Drive the attempt counter to the cap without an intervening successful open.
            logic.actions.sseReconnecting(MAX_SSE_RECONNECT_ATTEMPTS)

            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('error')
        })

        it('maps a refetch failure through the HTTP-status table', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockRejectedValue({ status: 404 })

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('error')
        })
    })

    describe('bootstrapRun', () => {
        it('skips logs/ and opens SSE directly on the fresh-run fast path', async () => {
            const logsSpy = jest.spyOn(api.tasks.runs, 'getLogEntries')

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1', justCreatedRun: true })
            await flushPromises()

            expect(logsSpy).not.toHaveBeenCalled()
            expect(MockEventSource.instances.length).toEqual(1)
            expect(MockEventSource.latest().url).not.toContain('start=latest')
        })

        it('replays logs/ then opens SSE with start=latest for a non-terminal run', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({ sessionUpdate: 'agent_message', messageId: 'm1', content: { text: 'history' } }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.runStarted).toEqual(true)
            const assistantItem = logic.values.threadItems.find((item) => item.type === 'assistant_message')
            expect(assistantItem?.text).toEqual('history')
            expect(MockEventSource.latest().url).toContain('start=latest')
        })

        it('replays logs/ and stays read-only for a terminal run', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.currentRunStatus).toEqual('completed')
            expect(MockEventSource.instances.length).toEqual(0)
        })
    })

    describe('wire frame parsing through onmessage', () => {
        it('reads the snake_case error_message off task_run_state frames', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            const source = MockEventSource.latest()
            source.emitOpen()

            await expectLogic(logic, () => {
                source.onmessage?.({
                    data: JSON.stringify({
                        type: 'task_run_state',
                        run_id: 'run-1',
                        task_id: 'task-1',
                        status: 'failed',
                        error_message: 'sandbox exploded',
                    }),
                } as MessageEvent<string>)
            }).toDispatchActions([
                (action) =>
                    action.type === logic.actionTypes.handleTerminalStatus &&
                    action.payload.status === 'failed' &&
                    action.payload.errorMessage === 'sandbox exploded',
            ])

            expect(logic.values.currentRunStatus).toEqual('failed')
            expect(source.closed).toEqual(true)
        })

        it('keeps the stream open for non-terminal task_run_state frames', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            const source = MockEventSource.latest()
            source.emitOpen()

            await expectLogic(logic, () => {
                source.onmessage?.({
                    data: JSON.stringify({ type: 'task_run_state', status: 'in_progress', error_message: null }),
                } as MessageEvent<string>)
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('in_progress')
            expect(source.closed).toEqual(false)
        })

        it('ignores unrecognized frame types', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            const source = MockEventSource.latest()
            source.emitOpen()

            source.onmessage?.({
                data: JSON.stringify({ type: 'telemetry_v2', payload: { value: 1 } }),
            } as MessageEvent<string>)

            expect(logic.values.threadItems).toEqual([])
            expect(logic.cache.ingestedEntryHashes.size).toEqual(0)
        })
    })

    describe('_posthog/progress handling', () => {
        it('renders the emitter label as current progress', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', {
                        sessionId: 's',
                        step: 'clone_repository',
                        status: 'in_progress',
                        label: 'Cloning repository',
                        group: 'setup',
                    })
                )
            }).toMatchValues({ currentProgress: 'Cloning repository' })
        })

        it('falls back to detail when label is absent', async () => {
            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    notification('_posthog/progress', { sessionId: 's', detail: 'PostHog/posthog @ master' })
                )
            }).toMatchValues({ currentProgress: 'PostHog/posthog @ master' })
        })
    })

    describe('mixed notification replay', () => {
        it('ingests known, unknown, and degenerate notifications without throwing, hashing each once', async () => {
            const corpus: StoredLogEntry[] = [
                notification('_posthog/run_started', { runId: 'run-1' }),
                notification('_posthog/usage_update', { used: { inputTokens: 1 }, cost: null }),
                notification('_posthog/hologram_sync', { shards: 3 }),
                { type: 'notification', notification: { method: '_posthog/turn_complete' } },
                { type: 'notification', notification: { method: '_posthog/console', params: 'not-an-object' as any } },
                sessionUpdate({ sessionUpdate: 'plan_delta', entries: [] }),
                sessionUpdate({ sessionUpdate: 'agent_message_chunk', text: 'hi' }),
            ]

            await expectLogic(logic, () => {
                corpus.forEach((entry) => logic.actions.ingestAcpFrame(entry))
            }).toFinishAllListeners()

            // Dedup hashing operates on the notification body — every distinct frame hashes once.
            expect(logic.cache.ingestedEntryHashes.size).toEqual(corpus.length)
        })
    })

    describe('telemetry parity', () => {
        it('emits TASK_RUN_STARTED once on the first run_started frame, always cold (wire carries no warmth)', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                // A stray cold_start hint on the wire is ignored — pre-warming isn't wired yet.
                logic.actions.ingestAcpFrame(notification('_posthog/run_started', { cold_start: false }))
                logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            }).toFinishAllListeners()

            const startedCalls = captureSpy.mock.calls.filter((c) => c[0] === 'task_run_started')
            expect(startedCalls.length).toEqual(1)
            expect(startedCalls[0][1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    run_id: 'run-1',
                    task_id: 'task-1',
                    execution_type: 'sandbox',
                    cold_start: true,
                })
            )
        })

        it('emits TASK_RUN_TERMINATED with duration_ms measured from run start', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
                logic.actions.handleTerminalStatus({ status: 'failed', errorMessage: 'boom' })
            }).toFinishAllListeners()

            const call = captureSpy.mock.calls.find((c) => c[0] === 'task_run_terminated')
            expect(call?.[1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    run_id: 'run-1',
                    status: 'failed',
                    error_message: 'boom',
                    execution_type: 'sandbox',
                })
            )
            expect((call![1] as any).duration_ms).toBeGreaterThanOrEqual(0)
        })

        it('emits TOOL_CALL_COMPLETED once when a tool call reaches a terminal status', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 't1',
                        serverName: 'posthog',
                        toolName: 'exec',
                        rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                        status: 'in_progress',
                    })
                )
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' })
                )
                // A second terminal update must not re-emit.
                logic.actions.ingestAcpFrame(
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' })
                )
            }).toFinishAllListeners()

            const toolCalls = captureSpy.mock.calls.filter((c) => c[0] === 'tool_call_completed')
            expect(toolCalls.length).toEqual(1)
            expect(toolCalls[0][1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    tool_call_id: 't1',
                    tool_qualified_name: 'execute-sql',
                    status: 'completed',
                    execution_type: 'sandbox',
                })
            )
        })

        it('forwards the trace_id to the permission endpoint for PERMISSION_RESPONDED correlation', async () => {
            const permissionSpy = jest.spyOn(api.conversations, 'permission').mockResolvedValue({ status: 'ok' } as any)
            logic.actions.openSseForRun({
                taskId: 'task-1',
                runId: 'run-1',
                traceId: 'trace-1',
            })

            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    conversationId: 'conv-1',
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()

            expect(permissionSpy).toHaveBeenCalledWith(
                'conv-1',
                expect.objectContaining({ requestId: 'req-1', optionId: 'allow_once', traceId: 'trace-1' })
            )
        })

        it('suppresses run lifecycle telemetry while replaying history on bootstrap', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/run_started', {}) as any,
                sessionUpdate({
                    sessionUpdate: 'tool_call',
                    toolCallId: 't1',
                    serverName: 'posthog',
                    toolName: 'exec',
                    rawInput: { command: 'call execute-sql {"query":"select 1"}' },
                    status: 'in_progress',
                }) as any,
                sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 't1', status: 'completed' }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'completed' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            // History is folded in (run marked started, status terminal) but none of the lifecycle
            // events re-fire — the run lived and died in a prior session.
            expect(logic.values.runStarted).toEqual(true)
            expect(logic.values.currentRunStatus).toEqual('completed')
            const lifecycleEvents = ['task_run_started', 'task_run_terminated', 'tool_call_completed']
            expect(captureSpy.mock.calls.filter((c) => lifecycleEvents.includes(c[0] as string))).toEqual([])
        })
    })

    describe('crash affordance', () => {
        it('pushes a crash-variant error item and still captures task_run_terminated', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1', traceId: 'trace-1' })

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({
                    status: 'failed',
                    errorMessage: 'Agent server crashed: boom',
                })
            }).toFinishAllListeners()

            const errorItem = logic.values.threadItems.find((item) => item.type === 'error')
            expect(errorItem?.variant).toEqual('crash')
            expect(errorItem?.errorMessage).toEqual('Agent server crashed: boom')
            // The existing termination telemetry is unchanged.
            const terminated = captureSpy.mock.calls.find((c) => c[0] === 'task_run_terminated')
            expect(terminated?.[1]).toEqual(
                expect.objectContaining({ status: 'failed', error_message: 'Agent server crashed: boom' })
            )
        })

        it('renders a plain failed run without the crash prefix as a raw error item', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'failed', errorMessage: 'usage limit reached' })
            }).toFinishAllListeners()

            const errorItem = logic.values.threadItems.find((item) => item.type === 'error')
            expect(errorItem?.variant).toEqual('error')
            expect(errorItem?.errorMessage).toEqual('usage limit reached')
        })

        it('does not push an error item for a failed run carrying no error message', async () => {
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })

            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'failed' })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.some((item) => item.type === 'error')).toEqual(false)
        })

        it('does not push an error item for a failed run replayed from history', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({
                    status: 'failed',
                    errorMessage: 'Agent server crashed: old',
                    replayedFromHistory: true,
                })
            }).toFinishAllListeners()

            expect(logic.values.threadItems.some((item) => item.type === 'error')).toEqual(false)
        })
    })

    describe('stream-disconnect telemetry', () => {
        it('captures sandbox_stream_disconnected with attempt counters and pushes a visible error item', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1', traceId: 'trace-1' })
            // Drive the per-drop counter to the cap so the next drop exhausts the budget.
            logic.actions.sseReconnecting(MAX_SSE_RECONNECT_ATTEMPTS)

            logic.actions.sseDropped()
            await flushPromises()

            expect(logic.values.sseStatus).toEqual('error')
            const disconnect = captureSpy.mock.calls.find((c) => c[0] === 'sandbox_stream_disconnected')
            expect(disconnect?.[1]).toEqual(
                expect.objectContaining({
                    conversation_id: 'test-conversation',
                    trace_id: 'trace-1',
                    run_id: 'run-1',
                    task_id: 'task-1',
                    error_title: 'Cloud stream failed',
                    retryable: true,
                    reconnect_attempts: MAX_SSE_RECONNECT_ATTEMPTS,
                    cumulative_reconnect_attempts: 1,
                    was_bootstrapping: false,
                    execution_type: 'sandbox',
                })
            )
            expect(logic.values.threadItems.some((item) => item.type === 'error')).toEqual(true)
        })

        it('reports was_bootstrapping=true when the run never connected before erroring', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockRejectedValue({ status: 500 })

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            const disconnect = captureSpy.mock.calls.find((c) => c[0] === 'sandbox_stream_disconnected')
            expect(disconnect?.[1]).toEqual(expect.objectContaining({ was_bootstrapping: true }))
        })
    })

    describe('stream phase', () => {
        it('is provisioning while the stream is open before run_started, then flips to thinking', async () => {
            expect(logic.values.streamPhase).toEqual('idle')

            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            MockEventSource.latest().emitOpen()

            // SSE open, agent not started yet — provisioning, surfacing _posthog/progress.
            logic.actions.ingestAcpFrame(notification('_posthog/progress', { label: 'Setting up sandbox' }))
            expect(logic.values.streamPhase).toEqual('provisioning')
            expect(logic.values.currentProgress).toEqual('Setting up sandbox')

            // run_started arrives — phase flips to thinking.
            logic.actions.ingestAcpFrame(notification('_posthog/run_started', {}))
            expect(logic.values.streamPhase).toEqual('thinking')

            // turn_complete ends the turn — back to idle.
            logic.actions.ingestAcpFrame(notification('_posthog/turn_complete', {}))
            expect(logic.values.streamPhase).toEqual('idle')
        })

        it('tracks the optional task_run_state stage off the wire', async () => {
            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toFinishAllListeners()
            const source = MockEventSource.latest()
            source.emitOpen()

            await expectLogic(logic, () => {
                source.onmessage?.({
                    data: JSON.stringify({ type: 'task_run_state', status: 'in_progress', stage: 'build' }),
                } as MessageEvent<string>)
            }).toFinishAllListeners()

            expect(logic.values.currentStage).toEqual('build')
        })
    })

    describe('reconnect refinements', () => {
        it('forgives a healthy connection drop — no reconnectAttempt increment but still schedules a reopen', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockEventSource.latest()

            jest.useFakeTimers()
            // sseOpened stamps cache.sseConnectedAtMs; advance past the healthy threshold before dropping.
            source.emitOpen()
            const beforeDrop = MockEventSource.instances.length
            jest.advanceTimersByTime(SSE_HEALTHY_CONNECTION_MS + 1_000)

            logic.actions.sseDropped()
            await flushPromises()

            // Healthy drop: per-drop budget untouched, but cumulative still grows and a reopen is scheduled.
            expect(logic.values.reconnectAttempt).toEqual(0)
            expect(logic.values.cumulativeReconnectAttempt).toEqual(1)
            expect(logic.values.sseStatus).toEqual('reconnecting')

            jest.advanceTimersByTime(SSE_RECONNECT_BASE_DELAY_MS)
            expect(MockEventSource.instances.length).toEqual(beforeDrop + 1)
            jest.useRealTimers()
        })

        it('fails on the cumulative cap even when the per-drop counter keeps resetting', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            MockEventSource.latest().emitOpen()
            // Drive the cumulative counter to the cap without growing the per-drop counter, as a
            // clean-EOF reopen loop would (every reopen resets reconnectAttempt to 0).
            for (let i = 0; i < MAX_CUMULATIVE_RECONNECT_ATTEMPTS; i++) {
                logic.actions.sseReconnecting(0)
            }
            expect(logic.values.cumulativeReconnectAttempt).toEqual(MAX_CUMULATIVE_RECONNECT_ATTEMPTS)

            logic.actions.sseDropped()
            await flushPromises()

            // The (cumulative + 1)th reconnect crosses the bound → terminal error.
            expect(logic.values.sseStatus).toEqual('error')
        })
    })

    describe('permission_request ingest', () => {
        // A destructive exec (`insight-update`) so the default policy prompts (shows a card) rather
        // than auto-approving — the lifecycle tests below all assume a card appears.
        const permissionFrame: PermissionRequestFrame = {
            type: 'permission_request',
            requestId: 'req-1',
            toolCall: {
                toolCallId: 't1',
                serverName: 'posthog',
                toolName: 'exec',
                _meta: { claudeCode: { toolName: 'mcp__posthog__exec' } },
                rawInput: { command: 'call insight-update {"id":"abc"}' },
                title: 'Update insight',
                status: 'pending',
            },
            options: [
                { optionId: 'allow_once', name: 'Approve', kind: 'allow_once' },
                { optionId: 'reject', name: 'Decline', kind: 'reject' },
            ],
        }

        it('parses a permission_request frame into a PermissionRequestRecord', () => {
            const record = parsePermissionRequestFrame(permissionFrame)
            expect(record).not.toBeNull()
            expect(record?.requestId).toEqual('req-1')
            expect(record?.toolCallId).toEqual('t1')
            expect(record?.toolName).toEqual('mcp__posthog__exec')
            expect(record?.options.map((o) => o.kind)).toEqual(['allow_once', 'reject'])
            expect(record?.rawToolCall.resolvedKey).toEqual('insight-update')
        })

        it('returns null for a frame with no usable options', () => {
            expect(parsePermissionRequestFrame({ ...permissionFrame, options: [] })).toBeNull()
            expect(parsePermissionRequestFrame({ type: 'permission_request', requestId: 'r', toolCall: {} })).toBeNull()
        })

        it('keeps a reject_once option and parses _meta.customInput (the previously-dropped decline)', () => {
            // Exact shape the agent adapter emits (see ee/hogai/sandbox/log.jsonl): the decline option
            // is `reject_once` carrying `_meta.customInput`, which the old exact-match allowlist dropped.
            const frame = {
                type: 'permission_request',
                requestId: 'req-2',
                toolCall: { toolCallId: 't2', title: 'exec' },
                options: [
                    { optionId: 'allow', name: 'Yes', kind: 'allow_once' },
                    { optionId: 'allow_always', name: 'Yes, always allow', kind: 'allow_always' },
                    {
                        optionId: 'reject',
                        name: 'No, and tell the agent what to do differently',
                        kind: 'reject_once',
                        _meta: { customInput: true },
                    },
                ],
            }
            const record = parsePermissionRequestFrame(frame as unknown as PermissionRequestFrame)
            expect(record?.options.map((o) => o.kind)).toEqual(['allow_once', 'allow_always', 'reject_once'])
            expect(record?.options.find((o) => o.kind === 'reject_once')?.customInput).toEqual(true)
        })

        it('names the inner tool when the toolCall carries _meta.claudeCode.toolName', () => {
            const record = parsePermissionRequestFrame({
                type: 'permission_request',
                requestId: 'req-2',
                toolCall: {
                    toolCallId: 't9',
                    title: 'Edit `app.ts`',
                    status: 'pending',
                    _meta: { claudeCode: { toolName: 'Edit' } },
                },
                options: [{ optionId: 'allow_once', name: 'Approve', kind: 'allow_once' }],
            })
            expect(record).not.toBeNull()
            expect(record?.rawToolCall.resolvedKey).toEqual('Edit')
            expect(record?.rawToolCall.claudeToolName).toEqual('Edit')
        })

        it('populates pendingPermissionRequest off a permission_request SSE frame', async () => {
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)

            await expectLogic(logic, () => {
                MockEventSource.latest().emitMessage({ ...permissionFrame })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            expect(logic.values.pendingPermissionRequest?.toolCallId).toEqual('t1')
            expect(captureSpy).toHaveBeenCalledWith(
                'permission_requested',
                expect.objectContaining({ request_id: 'req-1', execution_type: 'sandbox' })
            )
        })

        it('auto-approves a non-destructive PostHog exec without showing a card', async () => {
            const permissionSpy = jest.spyOn(api.conversations, 'permission').mockResolvedValue({ status: 'ok' } as any)
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockEventSource.latest()

            await expectLogic(logic, () => {
                source.emitMessage({
                    ...permissionFrame,
                    requestId: 'req-auto',
                    toolCall: {
                        ...permissionFrame.toolCall,
                        rawInput: { command: 'call insight-create {"name":"x"}' },
                    },
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(permissionSpy).toHaveBeenCalledWith(
                'test-conversation',
                expect.objectContaining({ requestId: 'req-auto', optionId: 'allow_once' })
            )
            expect(captureSpy).toHaveBeenCalledWith(
                'permission_auto_approved',
                expect.objectContaining({ request_id: 'req-auto', execution_type: 'sandbox' })
            )
        })

        it('auto-approves a built-in tool without showing a card', async () => {
            const permissionSpy = jest.spyOn(api.conversations, 'permission').mockResolvedValue({ status: 'ok' } as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockEventSource.latest()

            await expectLogic(logic, () => {
                source.emitMessage({
                    type: 'permission_request',
                    requestId: 'req-bash',
                    toolCall: {
                        toolCallId: 't-bash',
                        _meta: { claudeCode: { toolName: 'Bash' } },
                        title: 'Bash',
                        rawInput: { command: 'ls -la' },
                    },
                    options: [{ optionId: 'allow', name: 'Yes', kind: 'allow_once' }],
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(permissionSpy).toHaveBeenCalledWith(
                'test-conversation',
                expect.objectContaining({ requestId: 'req-bash', optionId: 'allow' })
            )
        })

        it('falls back to a manual card when the auto-approve POST fails', async () => {
            jest.spyOn(api.conversations, 'permission').mockRejectedValue({ status: 502 })
            jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockEventSource.latest()

            await expectLogic(logic, () => {
                source.emitMessage({
                    ...permissionFrame,
                    requestId: 'req-fail',
                    toolCall: {
                        ...permissionFrame.toolCall,
                        rawInput: { command: 'call insight-create {"name":"x"}' },
                    },
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-fail')
        })

        it('clears the pending request and POSTs the reply on respondToPermission', async () => {
            const permissionSpy = jest.spyOn(api.conversations, 'permission').mockResolvedValue({ status: 'ok' } as any)
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)

            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    conversationId: 'conv-1',
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(logic.values.respondingToPermission).toEqual(false)
            expect(permissionSpy).toHaveBeenCalledWith('conv-1', {
                requestId: 'req-1',
                optionId: 'allow_once',
                customInput: undefined,
            })
        })

        it('keeps the card pending and surfaces an error when the reply POST fails', async () => {
            jest.spyOn(api.conversations, 'permission').mockRejectedValue({ status: 502 })
            const exceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
            const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => undefined as any)
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)

            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    conversationId: 'conv-1',
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            // A failed reply POST must not tear down the live stream — the run is still alive and
            // blocked on this approval; only the card's buttons re-enable for a retry.
            expect(logic.values.sseStatus).not.toEqual('error')
            expect(logic.values.respondingToPermission).toEqual(false)
            expect(exceptionSpy).toHaveBeenCalled()
            expect(toastSpy).toHaveBeenCalled()
        })

        it('ignores a replayed permission_request envelope once the request is resolved', async () => {
            jest.spyOn(api.conversations, 'permission').mockResolvedValue({ status: 'ok' } as any)
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockEventSource.latest()

            await expectLogic(logic, () => {
                source.emitMessage({ ...permissionFrame })
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.respondToPermission({
                    conversationId: 'conv-1',
                    requestId: 'req-1',
                    optionId: 'allow_once',
                })
            }).toFinishAllListeners()
            expect(logic.values.pendingPermissionRequest).toBeNull()

            // A reconnect's full replay re-delivers the envelope verbatim.
            await expectLogic(logic, () => {
                source.emitMessage({ ...permissionFrame })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
            expect(captureSpy).toHaveBeenCalledTimes(1)
        })

        it('does not double-capture telemetry when the same envelope arrives twice while pending', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            const source = MockEventSource.latest()

            await expectLogic(logic, () => {
                source.emitMessage({ ...permissionFrame })
                source.emitMessage({ ...permissionFrame })
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            expect(captureSpy).toHaveBeenCalledTimes(1)
        })

        it('re-derives a pending approval from a logged _posthog/permission_request without telemetry', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/permission_request', {
                    requestId: 'req-1',
                    toolCall: permissionFrame.toolCall,
                    options: permissionFrame.options,
                }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')
            expect(captureSpy).not.toHaveBeenCalled()
        })

        it('drops a logged permission_request that has a matching permission_resolved entry', async () => {
            jest.spyOn(api.tasks.runs, 'getLogEntries').mockResolvedValue([
                notification('_posthog/permission_request', {
                    requestId: 'req-1',
                    toolCall: permissionFrame.toolCall,
                    options: permissionFrame.options,
                }) as any,
                notification('_posthog/permission_resolved', { requestId: 'req-1', optionId: 'allow_once' }) as any,
            ])
            jest.spyOn(api.tasks.runs, 'get').mockResolvedValue({ status: 'in_progress' } as any)

            logic.actions.bootstrapRun({ taskId: 'task-1', runId: 'run-1' })
            await flushPromises()

            expect(logic.values.pendingPermissionRequest).toBeNull()
        })

        it('clears the pending card when another client resolves the request', async () => {
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)
            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')

            await expectLogic(logic, () => {
                logic.actions.ingestAcpFrame(notification('_posthog/permission_resolved', { requestId: 'req-1' }))
            }).toFinishAllListeners()

            expect(logic.values.pendingPermissionRequest).toBeNull()
        })

        it('drops the pending card when the run reaches a terminal status, but not before', () => {
            logic.actions.ingestPermissionRequest(parsePermissionRequestFrame(permissionFrame)!)

            logic.actions.handleTerminalStatus({ status: 'queued' })
            expect(logic.values.pendingPermissionRequest?.requestId).toEqual('req-1')

            logic.actions.handleTerminalStatus({ status: 'completed' })
            expect(logic.values.pendingPermissionRequest).toBeNull()
        })
    })
})

// Drain queued microtasks (chained `await`s in async listeners) without relying on timers, so it
// works under both real and fake timers.
async function flushPromises(): Promise<void> {
    for (let i = 0; i < 10; i++) {
        await Promise.resolve()
    }
}
