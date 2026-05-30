import { resolveToolKey } from './mcpToolRegistry'
import { EMPTY_STREAM_STATE, ingestAcpFrame, SandboxStreamState } from './sandboxStreamLogic'
import { StoredLogEntry } from './types/sandboxStreamTypes'

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

        it('pushes an inline error on _posthog/error', () => {
            const state = fold([[notification('_posthog/error', { message: 'boom' }), 'f1']])
            expect(state.threadItems).toEqual([{ kind: 'error', id: 'f1', message: 'boom' }])
        })

        it('ignores unrelated _posthog/* methods', () => {
            const state = fold([
                [notification('_posthog/console', { message: 'log line' }), 'f1'],
                [notification('_posthog/usage_update', { tokens: 10 }), 'f2'],
            ])
            expect(state).toEqual(EMPTY_STREAM_STATE)
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
})
