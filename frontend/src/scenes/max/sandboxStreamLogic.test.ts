import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import { initKeaTests } from '~/test/init'

import {
    mapHttpStatusToStreamError,
    MAX_SSE_RECONNECT_ATTEMPTS,
    reconnectDelayMs,
    resolveToolKey,
    sandboxStreamLogic,
    SSE_RECONNECT_MAX_DELAY_MS,
} from './sandboxStreamLogic'
import type { StoredLogEntry } from './types/sandboxStreamTypes'

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
        logic = sandboxStreamLogic()
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

        it('returns the wire name for non-exec MCP tools and built-ins', () => {
            expect(resolveToolKey('user-mcp', 'do_thing', {}).resolvedKey).toEqual('do_thing')
            expect(resolveToolKey('claude', 'TodoWrite', {}).resolvedKey).toEqual('TodoWrite')
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

        it('drives terminal status off handleTerminalStatus', async () => {
            await expectLogic(logic, () => {
                logic.actions.handleTerminalStatus({ status: 'completed' })
            }).toFinishAllListeners()

            expect(logic.values.currentRunStatus).toEqual('completed')
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
            expect(logic.values.ingestedEntryHashes.size).toEqual(1)
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
        it('maps HTTP statuses to error envelopes per § 4.4', () => {
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
            jest.useRealTimers()
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

        it('maps a refetch failure through the § 4.4 table', async () => {
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
})

// Drain queued microtasks (chained `await`s in async listeners) without relying on timers, so it
// works under both real and fake timers.
async function flushPromises(): Promise<void> {
    for (let i = 0; i < 10; i++) {
        await Promise.resolve()
    }
}
