import { buildTimeline } from './runEvents'

const update = (payload: Record<string, unknown>): Record<string, unknown> => ({
    type: 'notification',
    timestamp: '2026-09-14T10:00:00Z',
    notification: { jsonrpc: '2.0', method: 'session/update', params: { update: payload } },
})

describe('buildTimeline', () => {
    it('merges message chunks and applies tool call updates to the row of the call', () => {
        const rows = buildTimeline([
            update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Reading ' } }),
            update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'the code.' } }),
            update({ sessionUpdate: 'tool_call', toolCallId: 't1', title: 'Bash', status: 'pending' }),
            update({
                sessionUpdate: 'tool_call_update',
                toolCallId: 't1',
                status: 'completed',
                rawInput: { command: 'pnpm test' },
            }),
            update({ sessionUpdate: 'agent_message_chunk', content: { type: 'text', text: 'Done.' } }),
        ])

        expect(rows.map(({ kind, title, body }) => ({ kind, title, body }))).toEqual([
            { kind: 'assistant', title: 'Agent', body: 'Reading the code.' },
            { kind: 'tool', title: 'Bash', body: 'pnpm test' },
            { kind: 'assistant', title: 'Agent', body: 'Done.' },
        ])
        expect(rows[1]).toMatchObject({ status: 'completed' })
    })

    test.each([
        ['a string', 'just text'],
        ['null', null],
        ['an empty object', {}],
        ['an array', [1, 2]],
        ['an update with no type', update({ content: 42 })],
        ['a tool call with a non-object input', update({ sessionUpdate: 'tool_call', rawInput: 'ls', title: 7 })],
        ['a message chunk with no text', update({ sessionUpdate: 'agent_message_chunk', content: { type: 'image' } })],
        ['a new update type', update({ sessionUpdate: 'usage_snapshot', tokens: { in: 3 } })],
        ['a status notification', { notification: { method: '_posthog/sandbox_ready', params: null } }],
    ])('does not throw on %s', (_, frame) => {
        const rows = buildTimeline([frame as Record<string, unknown>])
        expect(rows.length).toBeLessThanOrEqual(1)
        for (const row of rows) {
            expect(typeof row.title).toBe('string')
        }
    })

    it('turns a frame with no renderer into a generic row named after its type', () => {
        expect(buildTimeline([update({ sessionUpdate: 'usage_snapshot' })])).toMatchObject([
            { kind: 'unknown', title: 'Usage snapshot', body: null },
        ])
    })
})
