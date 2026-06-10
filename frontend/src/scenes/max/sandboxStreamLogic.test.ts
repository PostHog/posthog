import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { resolveToolKey, sandboxStreamLogic } from './sandboxStreamLogic'
import type { StoredLogEntry } from './types/sandboxStreamTypes'

function notification(method: string, params: Record<string, unknown>): StoredLogEntry {
    return { type: 'notification', notification: { method, params } }
}

function sessionUpdate(update: Record<string, unknown>): StoredLogEntry {
    return notification('session/update', { update })
}

describe('sandboxStreamLogic', () => {
    let logic: ReturnType<typeof sandboxStreamLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sandboxStreamLogic({ conversationId: 'test-conversation' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
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
    })
})
