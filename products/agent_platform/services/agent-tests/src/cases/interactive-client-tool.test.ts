/**
 * Interactive (render-style) client tool dispatch: when the spec marks a
 * client tool `interactive: true`, the runner emits the `client_tool_call`
 * bus event so the dock can mount its inline UI, then returns a synthetic
 * "queued, awaiting user input" envelope from the tool's `execute`. The
 * loop unwinds cleanly, the worker hands the session back to the queue,
 * and the user has unbounded time to respond. When the frontend POSTs
 * the outcome to `/send` (with the `client_tool_result` payload variant),
 * ingress drops a `__POSTHOG_CLIENT_TOOL_RESULT__` marker into
 * `pending_inputs`. On resume, the driver's marker scanner synthesises a
 * wake message carrying the real outcome so the model sees it on its
 * next turn.
 *
 * This mirrors the production `set_secret` flow used by the agent
 * console's `<SecretInline>` form.
 */

import request from 'supertest'

import { buildCluster, closeSharedPool, Cluster, fauxCallTool, fauxText } from '../harness'

describe('interactive client tool dispatch: real e2e', () => {
    let c: Cluster

    beforeEach(async () => {
        c = await buildCluster()
    })

    afterEach(async () => {
        await c.teardown()
    })

    afterAll(async () => {
        await closeSharedPool()
    })

    it('park + wake round-trip: model calls tool → session goes idle → /send wakes → model sees result', async () => {
        // Turn 1: model calls the interactive tool, then ends with text.
        // Turn 2 (after wake): model summarises that the secret was set.
        c.setScript([
            fauxCallTool('set_secret', {
                agent_slug: 'demo',
                secret: 'PUN_API_KEY',
                purpose: 'Authenticate the puns endpoint',
            }),
            fauxText("I've asked you to enter the value."),
            fauxText('Got it — secret saved. Anything else?'),
        ])

        await c.deployAgent({
            slug: 'demo',
            spec: {
                tools: [
                    {
                        kind: 'client',
                        id: 'set_secret',
                        description: 'Punch out to the user to set one secret on the agent.',
                        interactive: true,
                        args_schema: {
                            type: 'object',
                            properties: {
                                agent_slug: { type: 'string' },
                                secret: { type: 'string' },
                                purpose: { type: 'string' },
                            },
                            required: ['agent_slug', 'secret'],
                        },
                    },
                ],
            },
        })

        // Subscribe to the bus so we can verify the `client_tool_call`
        // event still fires — the dock relies on this to mount the
        // inline form. The interactive path emits the event but skips
        // the in-process await; we should NOT see a matching
        // `client_tool_result` bus event (those only flow through the
        // legacy /client_tool_result path).
        const res = await request(c.ingress)
            .post('/agents/demo/run')
            .send({ message: 'set the puns key', supported_client_tools: ['set_secret'] })
        const sessionId = res.body.session_id as string
        const busEvents: Array<{ kind: string; data: Record<string, unknown> }> = []
        const unsub = c.bus.subscribe(sessionId, (e) => {
            busEvents.push({ kind: e.kind, data: e.data as Record<string, unknown> })
        })

        await c.drain()
        let session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')

        // The runner emitted `client_tool_call` so the dock would render
        // the inline form. No bus-level `client_tool_result` event,
        // because the interactive path skips that round-trip.
        const callEvent = busEvents.find((e) => e.kind === 'client_tool_call')
        expect(callEvent).toBeTruthy()
        expect(callEvent!.data.tool_id).toBe('set_secret')
        const callId = callEvent!.data.call_id as string
        expect(typeof callId).toBe('string')
        expect(callId.length).toBeGreaterThan(0)
        expect(busEvents.some((e) => e.kind === 'client_tool_result')).toBe(false)

        // The model saw the synthetic queued envelope as the tool's
        // result, so the conversation should contain it.
        const queuedToolResult = session!.conversation.find((m) => m.role === 'toolResult') as
            | { role: 'toolResult'; content: Array<{ type: string; text?: string }> }
            | undefined
        expect(queuedToolResult).toBeTruthy()
        const queuedBody = queuedToolResult!.content.find((c) => c.type === 'text')?.text ?? ''
        expect(queuedBody).toContain('"queued":true')
        expect(queuedBody).toContain('"interactive":true')

        // Simulate the dock's POST after the user submits the inline
        // form. New /send payload variant carries the outcome — ingress
        // drops a marker into pending_inputs + re-queues the session.
        const sendRes = await request(c.ingress)
            .post('/agents/demo/send')
            .send({
                session_id: sessionId,
                client_tool_result: {
                    call_id: callId,
                    result: { key: 'PUN_API_KEY', action: 'set' },
                },
            })
        expect(sendRes.status).toBe(200)

        // Marker landed; state went back to queued; conversation
        // untouched (the wake message is built on resume).
        const beforeResume = await c.queue.get(sessionId)
        expect(beforeResume!.state).toBe('queued')
        expect(beforeResume!.pending_inputs).toHaveLength(1)

        await c.drain()
        unsub()

        session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')
        expect(session!.pending_inputs).toHaveLength(0)

        // The wake message landed in conversation as a `user` role
        // entry whose text carries the outcome envelope — the model
        // saw it on the next turn and emitted the final text.
        const userMessages = session!.conversation.filter((m) => m.role === 'user')
        const wakeText = userMessages
            .map((m) => {
                const c = (m as { content: unknown }).content
                if (typeof c === 'string') {
                    return c
                }
                if (Array.isArray(c) && c[0] && c[0].type === 'text') {
                    return (c[0] as { text: string }).text
                }
                return ''
            })
            .find((t) => t.includes('"call_id"'))
        expect(wakeText).toBeTruthy()
        expect(wakeText).toContain(`"call_id":"${callId}"`)
        expect(wakeText).toContain('"ok":true')
        expect(wakeText).toContain('"key":"PUN_API_KEY"')

        // And the model's follow-up text (the third script entry) is
        // the final assistant turn.
        const assistantTurns = session!.conversation.filter((m) => m.role === 'assistant')
        const finalText = (assistantTurns.at(-1) as { content: Array<{ type: string; text?: string }> }).content[0].text
        expect(finalText).toBe('Got it — secret saved. Anything else?')
    })

    it('error variant: /send with `error` → wake envelope carries ok:false + error string', async () => {
        c.setScript([
            fauxCallTool('set_secret', { agent_slug: 'demo', secret: 'PUN_API_KEY' }),
            fauxText('Standing by.'),
            fauxText('Understood — I will not retry.'),
        ])

        await c.deployAgent({
            slug: 'demo',
            spec: {
                tools: [
                    {
                        kind: 'client',
                        id: 'set_secret',
                        description: 'Punch out to the user to set one secret on the agent.',
                        interactive: true,
                        args_schema: { type: 'object', properties: {}, additionalProperties: true },
                    },
                ],
            },
        })

        const res = await request(c.ingress)
            .post('/agents/demo/run')
            .send({ message: 'set it', supported_client_tools: ['set_secret'] })
        const sessionId = res.body.session_id as string
        const calls: string[] = []
        const unsub = c.bus.subscribe(sessionId, (e) => {
            if (e.kind === 'client_tool_call') {
                calls.push((e.data as { call_id: string }).call_id)
            }
        })

        await c.drain()
        unsub()
        expect(calls).toHaveLength(1)
        const callId = calls[0]

        await request(c.ingress)
            .post('/agents/demo/send')
            .send({
                session_id: sessionId,
                client_tool_result: { call_id: callId, error: 'user_cancelled' },
            })

        await c.drain()
        const session = await c.queue.get(sessionId)
        expect(session!.state).toBe('completed')

        const userMessages = session!.conversation.filter((m) => m.role === 'user')
        const wakeText = userMessages
            .map((m) => {
                const c = (m as { content: unknown }).content
                if (Array.isArray(c) && c[0] && c[0].type === 'text') {
                    return (c[0] as { text: string }).text
                }
                return ''
            })
            .find((t) => t.includes('"call_id"'))
        expect(wakeText).toContain('"ok":false')
        expect(wakeText).toContain('"error":"user_cancelled"')
    })
})
