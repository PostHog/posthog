import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'
import { ReadableStream as NodeReadableStream } from 'stream/web'

import { initKeaTests } from '~/test/init'

import { resolveToolKey } from './mcpToolRegistry'
import {
    buildPermissionRequestRecord,
    computeBackoffDelay,
    conversationIdFromKey,
    EMPTY_STREAM_STATE,
    ingestAcpFrame,
    isTerminalRunStatus,
    MAX_SSE_RECONNECT_ATTEMPTS,
    mapStatusToErrorEnvelope,
    sandboxStreamLogic,
    SandboxStreamState,
    serializeEntryForDedup,
} from './sandboxStreamLogic'
import { RunStatus, StoredLogEntry } from './types/sandboxStreamTypes'

describe('sandboxStreamLogic', () => {
    function notification(method: string, params?: Record<string, unknown>): StoredLogEntry {
        return { type: 'notification', notification: { jsonrpc: '2.0', method, params } }
    }

    function sessionUpdate(update: Record<string, unknown>): StoredLogEntry {
        return notification('session/update', { update })
    }

    function fold(entries: [StoredLogEntry, string][]): SandboxStreamState {
        return entries.reduce((state, [entry, id]) => ingestAcpFrame(state, entry, id), EMPTY_STREAM_STATE)
    }

    describe('ingestAcpFrame — agent messages', () => {
        it('buffers an agent_message_chunk as an incomplete assistant item', () => {
            const state = fold([
                [sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Hel' } }), 'f1'],
            ])
            expect(state.threadItems).toEqual([{ kind: 'assistant_message', id: 'f1', text: 'Hel', complete: false }])
        })

        it('appends consecutive chunks into the same incomplete buffer', () => {
            const state = fold([
                [sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Hel' } }), 'f1'],
                [sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'lo' } }), 'f2'],
            ])
            expect(state.threadItems).toEqual([{ kind: 'assistant_message', id: 'f1', text: 'Hello', complete: false }])
        })

        it('finalizes the buffer on agent_message', () => {
            const state = fold([
                [sessionUpdate({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Hi' } }), 'f1'],
                [sessionUpdate({ sessionUpdate: 'agent_message', content: { type: 'text', text: ' there' } }), 'f2'],
            ])
            expect(state.threadItems).toEqual([
                { kind: 'assistant_message', id: 'f1', text: 'Hi there', complete: true },
            ])
        })
    })

    describe('ingestAcpFrame — tool calls', () => {
        it('creates a ToolInvocation and a thread item on tool_call', () => {
            const state = fold([
                [
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 'tc-1',
                        title: 'exec',
                        status: 'in_progress',
                        rawInput: { command: 'call insight-create {"name":"Signups"}' },
                        _meta: { serverName: 'posthog', claudeCode: { toolName: 'exec' } },
                    }),
                    'f1',
                ],
            ])
            expect(state.threadItems).toEqual([{ kind: 'tool_invocation', toolCallId: 'tc-1' }])
            const tc = state.toolInvocations['tc-1']
            expect(tc.resolvedKey).toBe('insight-create')
            expect(tc.innerToolName).toBe('insight-create')
            expect(tc.innerInput).toEqual({ name: 'Signups' })
            expect(tc.status).toBe('in_progress')
        })

        it('merges a tool_call_update into the existing record without duplicating the thread item', () => {
            const state = fold([
                [
                    sessionUpdate({
                        sessionUpdate: 'tool_call',
                        toolCallId: 'tc-1',
                        status: 'in_progress',
                        rawInput: { command: 'call execute-sql {}' },
                        _meta: { serverName: 'posthog', claudeCode: { toolName: 'exec' } },
                    }),
                    'f1',
                ],
                [
                    sessionUpdate({
                        sessionUpdate: 'tool_call_update',
                        toolCallId: 'tc-1',
                        status: 'completed',
                        rawOutput: { rows: 3 },
                    }),
                    'f2',
                ],
            ])
            expect(state.threadItems).toEqual([{ kind: 'tool_invocation', toolCallId: 'tc-1' }])
            expect(state.toolInvocations['tc-1'].status).toBe('completed')
            expect(state.toolInvocations['tc-1'].output).toEqual({ rows: 3 })
        })

        it('ignores a tool_call_update for an unknown toolCallId', () => {
            const state = fold([
                [
                    sessionUpdate({ sessionUpdate: 'tool_call_update', toolCallId: 'missing', status: 'completed' }),
                    'f1',
                ],
            ])
            expect(state.toolInvocations).toEqual({})
            expect(state.threadItems).toEqual([])
        })

        it('detects a duplicate tool_call frame via serialized-JSON content equality', () => {
            const frame = sessionUpdate({
                sessionUpdate: 'tool_call',
                toolCallId: 'tc-dup',
                status: 'in_progress',
                rawInput: { command: 'call execute-sql {}' },
                _meta: { serverName: 'posthog', claudeCode: { toolName: 'exec' } },
            })
            // Same content, different frame ids (Redis vs S3-log) — the second must be deduped.
            const state = fold([
                [frame, 'log-0'],
                [frame, 'stream-99'],
            ])
            expect(state.threadItems).toEqual([{ kind: 'tool_invocation', toolCallId: 'tc-dup' }])
            expect(state.ingestedEntryHashes).toHaveLength(1)
        })
    })

    describe('ingestAcpFrame — lifecycle frames', () => {
        it('sets runStarted on _posthog/run_started', () => {
            expect(fold([[notification('_posthog/run_started'), 'f1']]).runStarted).toBe(true)
        })

        it('sets turnComplete and a separator on _posthog/turn_complete', () => {
            const state = fold([[notification('_posthog/turn_complete'), 'f1']])
            expect(state.turnComplete).toBe(true)
            expect(state.threadItems).toEqual([{ kind: 'turn_complete', id: 'f1' }])
        })

        it('captures progress on _posthog/progress', () => {
            expect(fold([[notification('_posthog/progress', { message: 'Querying' }), 'f1']]).currentProgress).toBe(
                'Querying'
            )
        })

        it('captures the mode on a current_mode_update session update', () => {
            const state = fold([[sessionUpdate({ sessionUpdate: 'current_mode_update', currentModeId: 'plan' }), 'f1']])
            expect(state.currentMode).toBe('plan')
        })

        it('pushes an inline error on _posthog/error', () => {
            const state = fold([[notification('_posthog/error', { message: 'boom' }), 'f1']])
            expect(state.threadItems).toEqual([{ kind: 'error', id: 'f1', message: 'boom' }])
        })

        it('ignores unrelated _posthog/* methods (no thread/tool effect)', () => {
            const state = fold([
                [notification('_posthog/console', { message: 'log line' }), 'f1'],
                [notification('_posthog/usage_update', { tokens: 10 }), 'f2'],
            ])
            // No renderable effect, but the frames are still tracked for content dedup.
            expect(state.threadItems).toEqual([])
            expect(state.toolInvocations).toEqual({})
            expect(state.runStarted).toBe(false)
            expect(state.turnComplete).toBe(false)
        })

        it('ignores malformed frames with no method', () => {
            const empty: StoredLogEntry = { type: 'notification', notification: { jsonrpc: '2.0' } }
            expect(fold([[empty, 'f1']])).toEqual(EMPTY_STREAM_STATE)
        })
    })

    describe('resolveToolKey', () => {
        it.each([
            [
                'exec call known inner tool',
                'posthog',
                'exec',
                { command: 'call insight-create {"a":1}' },
                'insight-create',
            ],
            [
                'exec call --json inner tool',
                'posthog',
                'exec',
                { command: 'call --json execute-sql {}' },
                'execute-sql',
            ],
            ['exec discovery verb tools', 'posthog', 'exec', { command: 'tools' }, '__posthog_exec_tools__'],
            ['exec discovery verb search', 'posthog', 'exec', { command: 'search foo' }, '__posthog_exec_search__'],
            ['exec malformed verb', 'posthog', 'exec', { command: 'frobnicate something' }, '__posthog_exec_unknown__'],
            ['exec malformed call body', 'posthog', 'exec', { command: 'call' }, '__posthog_exec_unknown__'],
            [
                'plugin_posthog regional exec',
                'plugin_posthog_us',
                'exec',
                { command: 'call notebooks-create {}' },
                'notebooks-create',
            ],
            ['non-exec claude builtin', '', 'TodoWrite', {}, 'TodoWrite'],
            ['non-exec user MCP tool', 'github', 'create_issue', {}, 'create_issue'],
        ])('%s -> %s', (_name, serverName, toolName, input, expectedKey) => {
            expect(resolveToolKey(serverName, toolName, input as Record<string, unknown>).resolvedKey).toBe(expectedKey)
        })

        it('parses inner JSON input for a call verb', () => {
            const resolved = resolveToolKey('posthog', 'exec', { command: 'call insight-create {"name":"x"}' })
            expect(resolved.innerToolName).toBe('insight-create')
            expect(resolved.innerInput).toEqual({ name: 'x' })
        })

        it('leaves innerInput empty on unparseable JSON body', () => {
            const resolved = resolveToolKey('posthog', 'exec', { command: 'call insight-create {not json}' })
            expect(resolved.resolvedKey).toBe('insight-create')
            expect(resolved.innerInput).toEqual({})
        })
    })

    describe('computeBackoffDelay — capped exponential schedule', () => {
        it.each([
            [1, 2_000],
            [2, 4_000],
            [3, 8_000],
            [4, 16_000],
            [5, 30_000],
            [6, 30_000],
        ])('attempt %i -> %ims', (attempt, expected) => {
            expect(computeBackoffDelay(attempt)).toBe(expected)
        })

        it('produces the documented 2/4/8/16/30 schedule across the max attempts', () => {
            const schedule = Array.from({ length: MAX_SSE_RECONNECT_ATTEMPTS }, (_, i) => computeBackoffDelay(i + 1))
            expect(schedule).toEqual([2_000, 4_000, 8_000, 16_000, 30_000])
        })
    })

    describe('mapStatusToErrorEnvelope — error-class table', () => {
        it.each<[number | undefined, string, boolean]>([
            [401, 'Cloud authentication expired', true],
            [403, 'Cloud access denied', true],
            [406, 'Cloud stream unavailable', true],
            [500, 'Cloud stream failed', true],
            [undefined, 'Cloud stream failed', true],
            [404, 'Conversation backing run not found', false],
        ])('%s -> %s (retryable=%s)', (status, errorTitle, retryable) => {
            expect(mapStatusToErrorEnvelope(status)).toEqual({ errorTitle, retryable })
        })
    })

    describe('isTerminalRunStatus', () => {
        it.each<[RunStatus | undefined, boolean]>([
            ['queued', false],
            ['in_progress', false],
            ['completed', true],
            ['failed', true],
            ['cancelled', true],
            [undefined, false],
        ])('%s -> %s', (status, terminal) => {
            expect(isTerminalRunStatus(status)).toBe(terminal)
        })
    })

    describe('serializeEntryForDedup', () => {
        it('hashes structurally-equal frames identically regardless of key order', () => {
            const a: StoredLogEntry = {
                type: 'notification',
                notification: { jsonrpc: '2.0', method: 'session/update', params: { update: { sessionUpdate: 'x' } } },
            }
            const b: StoredLogEntry = {
                type: 'notification',
                notification: { method: 'session/update', params: { update: { sessionUpdate: 'x' } }, jsonrpc: '2.0' },
            }
            expect(serializeEntryForDedup(a)).toBe(serializeEntryForDedup(b))
        })
    })

    describe('conversationIdFromKey', () => {
        it.each([
            ['019-abc-def-ghi-jkl-sidepanel', '019-abc-def-ghi-jkl'],
            ['11111111-2222-3333-4444-555555555555-scene', '11111111-2222-3333-4444-555555555555'],
            ['11111111-2222-3333-4444-555555555555-tab-7', '11111111-2222-3333-4444-555555555555'],
        ])('%s -> %s', (conversationKey, expected) => {
            expect(conversationIdFromKey(conversationKey)).toBe(expected)
        })
    })

    describe('ingestHistory — /log/ replay seeds dedup hashes', () => {
        beforeEach(() => {
            initKeaTests()
        })

        it('replays history into thread state and dedups a subsequent identical live frame', async () => {
            const historyFrame = sessionUpdate({
                sessionUpdate: 'agent_message',
                content: { type: 'text', text: 'From history' },
            })
            const logic = sandboxStreamLogic({ conversationKey: 'conv-history' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.ingestHistory([historyFrame])
            }).toMatchValues({
                threadItems: [{ kind: 'assistant_message', id: 'log-0', text: 'From history', complete: true }],
            })
            // The history frame seeded a dedup hash.
            expect(logic.values.stream.ingestedEntryHashes).toHaveLength(1)

            // A live SSE frame with identical content (different frame id) dedups against history.
            logic.actions.ingestFrame(historyFrame, 'stream-9')
            expect(logic.values.threadItems).toHaveLength(1)
            expect(logic.values.stream.ingestedEntryHashes).toHaveLength(1)
            logic.unmount()
        })
    })

    describe('currentMode selector — drives the mode badge', () => {
        beforeEach(() => {
            initKeaTests()
        })

        it('exposes the latest current_mode_update via the currentMode selector', () => {
            const logic = sandboxStreamLogic({ conversationKey: 'conv-mode' })
            logic.mount()
            expect(logic.values.currentMode).toBeUndefined()
            logic.actions.ingestFrame(
                sessionUpdate({ sessionUpdate: 'current_mode_update', currentModeId: 'plan' }),
                'f1'
            )
            expect(logic.values.currentMode).toBe('plan')
            logic.unmount()
        })
    })

    describe('buildPermissionRequestRecord — permission_request frame fold', () => {
        it('returns null when the frame lacks a request id', () => {
            expect(buildPermissionRequestRecord({ type: 'permission_request' })).toBeNull()
        })

        it('builds a record carrying options[] and a resolved tool call', () => {
            const record = buildPermissionRequestRecord({
                type: 'permission_request',
                requestId: 'req-1',
                description: 'Run a dangerous query',
                toolCall: {
                    toolCallId: 'tc-9',
                    title: 'execute_sql',
                    rawInput: { query: 'DROP TABLE x' },
                    _meta: { serverName: 'posthog', claudeCode: { toolName: 'execute_sql' } },
                },
                options: [
                    { optionId: 'opt-allow', name: 'Allow', kind: 'allow_once' },
                    { optionId: 'opt-reject', name: 'Reject', kind: 'reject' },
                ],
            })
            expect(record).not.toBeNull()
            expect(record!.requestId).toBe('req-1')
            expect(record!.toolCallId).toBe('tc-9')
            expect(record!.options).toHaveLength(2)
            expect(record!.rawToolCall.input).toEqual({ query: 'DROP TABLE x' })
            expect(record!.description).toBe('Run a dangerous query')
        })

        it('falls back to the request id as the tool call id when toolCall omits one', () => {
            const record = buildPermissionRequestRecord({ type: 'permission_request', requestId: 'req-2' })
            expect(record!.toolCallId).toBe('req-2')
            expect(record!.options).toEqual([])
        })

        it('carries the remember flag (drives the Always-allow affordance)', () => {
            expect(
                buildPermissionRequestRecord({ type: 'permission_request', requestId: 'req-3', remember: true })!
                    .remember
            ).toBe(true)
            expect(buildPermissionRequestRecord({ type: 'permission_request', requestId: 'req-4' })!.remember).toBe(
                false
            )
        })
    })

    describe('ingestPermissionRequest reducer — pending request + ordered thread item', () => {
        beforeEach(() => {
            initKeaTests()
        })

        it('exposes pendingPermissionRequest and appends one permission_request thread item idempotently', () => {
            const logic = sandboxStreamLogic({ conversationKey: 'conv-perm' })
            logic.mount()
            const record = buildPermissionRequestRecord({
                type: 'permission_request',
                requestId: 'req-1',
                options: [{ optionId: 'o', name: 'Allow', kind: 'allow_once' }],
            })!

            logic.actions.ingestPermissionRequest(record)
            expect(logic.values.pendingPermissionRequest).toEqual(record)
            expect(logic.values.threadItems).toEqual([{ kind: 'permission_request', requestId: 'req-1' }])

            // A re-delivered frame (reconnect replay) does not append a second card.
            logic.actions.ingestPermissionRequest(record)
            expect(logic.values.threadItems).toEqual([{ kind: 'permission_request', requestId: 'req-1' }])
            logic.unmount()
        })
    })

    describe('handleTerminalStatus — telemetry parity', () => {
        let captureSpy: jest.SpyInstance

        beforeEach(() => {
            initKeaTests()
            captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        })

        afterEach(() => {
            captureSpy.mockRestore()
        })

        it.each<[RunStatus, string]>([
            ['completed', 'success'],
            ['failed', 'failure'],
            ['cancelled', 'cancelled'],
        ])(
            'emits the existing turn-completed event with execution_type sandbox on %s',
            (terminalStatus, expectedStatus) => {
                const logic = sandboxStreamLogic({ conversationKey: '11111111-2222-3333-4444-555555555555-scene' })
                logic.mount()
                // openSseForRun retains the run ref the telemetry references.
                logic.actions.openSseForRun({ taskId: 'task-9', runId: 'run-9' })
                logic.actions.handleTerminalStatus(terminalStatus)

                expect(captureSpy).toHaveBeenCalledWith('max conversation turn completed', {
                    status: expectedStatus,
                    conversation_id: '11111111-2222-3333-4444-555555555555',
                    run_id: 'run-9',
                    task_id: 'task-9',
                    execution_type: 'sandbox',
                    agent_runtime: 'sandbox',
                })
                logic.unmount()
            }
        )
    })

    describe('openSseForRun listener — direct stream', () => {
        const originalFetch = global.fetch

        function buildReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
            const encoder = new TextEncoder()
            let index = 0
            const StreamConstructor = globalThis.ReadableStream ?? NodeReadableStream
            return new StreamConstructor({
                pull(controller) {
                    if (index < chunks.length) {
                        controller.enqueue(encoder.encode(chunks[index]))
                        index += 1
                    } else {
                        controller.close()
                    }
                },
            })
        }

        function streamResponse(chunks: string[]): Response {
            return { ok: true, status: 200, body: buildReadableStream(chunks) } as Response
        }

        function jsonResponse(payload: unknown): Response {
            return new Response(JSON.stringify(payload), { headers: { 'Content-Type': 'application/json' } })
        }

        function agentChunkFrame(id: string, text: string): string {
            return `id: ${id}\nevent: message\ndata: ${JSON.stringify({
                type: 'notification',
                notification: {
                    jsonrpc: '2.0',
                    method: 'session/update',
                    params: { update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text } } },
                },
            })}\n\n`
        }

        function taskRunStateFrame(id: string, status: RunStatus): string {
            return `id: ${id}\nevent: message\ndata: ${JSON.stringify({ type: 'task_run_state', status })}\n\n`
        }

        function permissionRequestFrame(id: string): string {
            return `id: ${id}\nevent: message\ndata: ${JSON.stringify({
                type: 'permission_request',
                requestId: 'req-1',
                description: 'Approve this?',
                toolCall: { toolCallId: 'tc-1', title: 'execute_sql', rawInput: { q: 'x' } },
                options: [{ optionId: 'o1', name: 'Allow', kind: 'allow_once' }],
            })}\n\n`
        }

        async function flushStreaming(): Promise<void> {
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
            await new Promise((resolve) => setTimeout(resolve, 0))
        }

        beforeEach(() => {
            initKeaTests()
        })

        afterEach(() => {
            jest.restoreAllMocks()
            global.fetch = originalFetch
        })

        it('dispatches connecting->open->status and ingestFrame from a mocked reader', async () => {
            const run: Partial<TaskRunLike> = { status: 'completed' }
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    return Promise.resolve(streamResponse([agentChunkFrame('1', 'Hello')]))
                }
                if (/\/runs\/[^/]+\/$/.test(url)) {
                    return Promise.resolve(jsonResponse(run))
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-1' })
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            }).toDispatchActions(['openSseForRun', 'setSseStatus'])

            await flushStreaming()

            // The agent chunk folded into a thread item via ingestFrame.
            expect(logic.values.threadItems).toEqual([
                { kind: 'assistant_message', id: 'stream-1', text: 'Hello', complete: false },
            ])
            // EOF -> REST refetch found a terminal run -> closed + terminal status driven.
            expect(logic.values.currentRunStatus).toBe('completed')
            expect(logic.values.isRunTerminal).toBe(true)
            logic.unmount()
        })

        it('drives a non-retryable error envelope on a 404 stream open', async () => {
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    return Promise.resolve({ ok: false, status: 404, body: null } as Response)
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-404' })
            logic.mount()
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushStreaming()

            expect(logic.values.streamError).toEqual({
                errorTitle: 'Conversation backing run not found',
                retryable: false,
            })
            expect(logic.values.sseStatus).toBe('error')
            logic.unmount()
        })

        it('consumes a permission_request control frame into pendingPermissionRequest', async () => {
            const run: Partial<TaskRunLike> = { status: 'completed' }
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    return Promise.resolve(streamResponse([permissionRequestFrame('1')]))
                }
                if (/\/runs\/[^/]+\/$/.test(url)) {
                    return Promise.resolve(jsonResponse(run))
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-perm-sse' })
            logic.mount()
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushStreaming()

            expect(logic.values.pendingPermissionRequest?.requestId).toBe('req-1')
            expect(logic.values.pendingPermissionRequest?.toolCallId).toBe('tc-1')
            expect(logic.values.pendingPermissionRequest?.options).toHaveLength(1)
            expect(logic.values.threadItems).toContainEqual({ kind: 'permission_request', requestId: 'req-1' })
            logic.unmount()
        })

        it('closes the stream and drives terminal on a terminal task_run_state frame', async () => {
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    return Promise.resolve(streamResponse([taskRunStateFrame('1', 'failed')]))
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-terminal' })
            logic.mount()
            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await flushStreaming()

            // Terminal status closes the stream without waiting for a REST refetch on EOF.
            expect(logic.values.currentRunStatus).toBe('failed')
            expect(logic.values.isRunTerminal).toBe(true)
            expect(logic.values.sseStatus).toBe('closed')
            logic.unmount()
        })
    })

    describe('openSseForRun listener — reconnect loop (fake timers)', () => {
        const originalFetch = global.fetch

        function buildReadableStream(chunks: string[]): ReadableStream<Uint8Array> {
            const encoder = new TextEncoder()
            let index = 0
            const StreamConstructor = globalThis.ReadableStream ?? NodeReadableStream
            return new StreamConstructor({
                pull(controller) {
                    if (index < chunks.length) {
                        controller.enqueue(encoder.encode(chunks[index]))
                        index += 1
                    } else {
                        controller.close()
                    }
                },
            })
        }

        function streamResponse(chunks: string[]): Response {
            return { ok: true, status: 200, body: buildReadableStream(chunks) } as Response
        }

        function jsonResponse(payload: unknown): Response {
            return new Response(JSON.stringify(payload), { headers: { 'Content-Type': 'application/json' } })
        }

        function agentChunkFrame(id: string, text: string): string {
            return `id: ${id}\nevent: message\ndata: ${JSON.stringify({
                type: 'notification',
                notification: {
                    jsonrpc: '2.0',
                    method: 'session/update',
                    params: { update: { sessionUpdate: 'agent_message_chunk', content: { type: 'text', text } } },
                },
            })}\n\n`
        }

        beforeEach(() => {
            initKeaTests()
            jest.useFakeTimers()
        })

        afterEach(() => {
            // Drain any timer left dangling by an unfinished reconnect chain before restoring.
            jest.clearAllTimers()
            jest.useRealTimers()
            jest.restoreAllMocks()
            global.fetch = originalFetch
        })

        it('schedules a reconnect at the computed backoff delay after an open-then-EOF drop on a non-terminal run', async () => {
            // /stream/ opens then immediately EOFs with no terminal frame; /runs/ reports the
            // backing run is still in_progress -> the drop is retryable, not terminal.
            const run: TaskRunLike = { status: 'in_progress' }
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    return Promise.resolve(streamResponse([]))
                }
                if (/\/runs\/[^/]+\/$/.test(url)) {
                    return Promise.resolve(jsonResponse(run))
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-reconnect' })
            logic.mount()

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            // Flush the open + EOF + REST refetch, all of which resolve as microtasks (no timer yet).
            await jest.advanceTimersByTimeAsync(0)

            // The first drop scheduled a reconnect: status flipped to reconnecting, attempt is 1.
            expect(logic.values.sseStatus).toBe('reconnecting')
            expect(logic.values.reconnectAttempt).toBe(1)
            // No retry has actually fired yet — the timer is armed at the base backoff delay.
            const fetchMock = global.fetch as jest.Mock
            const streamCallsBeforeDelay = fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/stream/')).length
            expect(streamCallsBeforeDelay).toBe(1)

            // Just before the computed delay, the retry must NOT have fired.
            await jest.advanceTimersByTimeAsync(computeBackoffDelay(1) - 1)
            const streamCallsJustBeforeFire = fetchMock.mock.calls.filter(([u]) =>
                String(u).endsWith('/stream/')
            ).length
            expect(streamCallsJustBeforeFire).toBe(1)

            // Crossing the delay fires exactly one reconnect attempt (a second /stream/ open).
            await jest.advanceTimersByTimeAsync(1)
            const streamCallsAfterFire = fetchMock.mock.calls.filter(([u]) => String(u).endsWith('/stream/')).length
            expect(streamCallsAfterFire).toBe(2)

            logic.unmount()
        })

        it('counts consecutive open-then-EOF cycles toward the cap and errors out after MAX attempts', async () => {
            // Every /stream/ open EOFs with no frame ingested; every /runs/ refetch is non-terminal.
            // FIX 2: bare 'open' must NOT reset reconnectAttempt — only a real frame ingest does —
            // so these open-then-EOF cycles accumulate toward MAX_SSE_RECONNECT_ATTEMPTS.
            const run: TaskRunLike = { status: 'in_progress' }
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    return Promise.resolve(streamResponse([]))
                }
                if (/\/runs\/[^/]+\/$/.test(url)) {
                    return Promise.resolve(jsonResponse(run))
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-cap' })
            logic.mount()

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.reconnectAttempt).toBe(1)
            expect(logic.values.sseStatus).toBe('reconnecting')

            // Walk the schedule: each backoff delay opens, EOFs, refetches non-terminal, reschedules.
            // After MAX_SSE_RECONNECT_ATTEMPTS scheduled retries, the next drop trips the cap.
            for (let attempt = 1; attempt <= MAX_SSE_RECONNECT_ATTEMPTS; attempt++) {
                await jest.advanceTimersByTimeAsync(computeBackoffDelay(attempt))
            }

            // The (MAX+1)th drop exceeds the cap -> retryable error envelope + error status, no further retries.
            expect(logic.values.sseStatus).toBe('error')
            expect(logic.values.streamError).toEqual({ errorTitle: 'Cloud stream failed', retryable: true })
            expect(logic.values.reconnectAttempt).toBe(MAX_SSE_RECONNECT_ATTEMPTS)

            logic.unmount()
        })

        it('resets the attempt counter only after a real frame ingest, not on bare open', async () => {
            // First open carries a real frame (counter resets to 0 on ingest), then EOFs.
            // Second open carries NO frame and EOFs -> the post-ingest reset means this counts
            // as attempt 1 again, proving the reset is keyed to ingestFrame, not setSseStatus('open').
            const run: TaskRunLike = { status: 'in_progress' }
            let streamOpens = 0
            global.fetch = jest.fn((input: RequestInfo | URL) => {
                const url = String(input)
                if (url.endsWith('/stream/')) {
                    streamOpens += 1
                    // Only the first open carries a frame; subsequent opens are bare open-then-EOF.
                    return Promise.resolve(streamResponse(streamOpens === 1 ? [agentChunkFrame('1', 'Hi')] : []))
                }
                if (/\/runs\/[^/]+\/$/.test(url)) {
                    return Promise.resolve(jsonResponse(run))
                }
                throw new Error(`Unexpected fetch url: ${url}`)
            }) as typeof fetch

            const logic = sandboxStreamLogic({ conversationKey: 'conv-frame-reset' })
            logic.mount()

            logic.actions.openSseForRun({ taskId: 'task-1', runId: 'run-1' })
            await jest.advanceTimersByTimeAsync(0)

            // The frame folded in and the run is non-terminal, so a reconnect is scheduled.
            // The frame ingest reset the counter, so this first reconnect is attempt 1.
            expect(logic.values.threadItems).toEqual([
                { kind: 'assistant_message', id: 'stream-1', text: 'Hi', complete: false },
            ])
            expect(logic.values.reconnectAttempt).toBe(1)

            // Fire the reconnect: the second open is bare open-then-EOF (no frame). Because the
            // counter was reset by the earlier ingest, this advances to attempt 2 — it does NOT
            // reset to 0 on the bare 'open'.
            await jest.advanceTimersByTimeAsync(computeBackoffDelay(1))
            expect(logic.values.reconnectAttempt).toBe(2)
            expect(logic.values.sseStatus).toBe('reconnecting')

            logic.unmount()
        })
    })
})

interface TaskRunLike {
    status: RunStatus
}
