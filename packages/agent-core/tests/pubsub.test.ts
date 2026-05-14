import { InMemorySessionBus, SessionEvent, SessionInputMessage } from '../src'

describe('InMemorySessionBus', () => {
    let bus: InMemorySessionBus

    beforeEach(() => {
        bus = new InMemorySessionBus()
    })

    afterEach(async () => {
        await bus.disconnect()
    })

    it('delivers events to a subscriber', async () => {
        const received: SessionEvent[] = []
        const unsubscribe = await bus.subscribeEvents('s1', (event) => {
            received.push(event)
        })

        await bus.publishEvent('s1', { type: 'turn_started', at: '2026-05-14T00:00:00Z' })
        await bus.publishEvent('s1', { type: 'turn_completed', at: '2026-05-14T00:00:01Z' })

        expect(received).toEqual([
            { type: 'turn_started', at: '2026-05-14T00:00:00Z' },
            { type: 'turn_completed', at: '2026-05-14T00:00:01Z' },
        ])

        await unsubscribe()
        await bus.publishEvent('s1', { type: 'turn_started', at: '2026-05-14T00:00:02Z' })
        expect(received).toHaveLength(2)
    })

    it('separates events for different sessions', async () => {
        const oneReceived: SessionEvent[] = []
        const twoReceived: SessionEvent[] = []
        await bus.subscribeEvents('s1', (event) => oneReceived.push(event))
        await bus.subscribeEvents('s2', (event) => twoReceived.push(event))

        await bus.publishEvent('s1', { type: 'turn_started', at: 't' })
        await bus.publishEvent('s2', { type: 'turn_completed', at: 't' })

        expect(oneReceived).toEqual([{ type: 'turn_started', at: 't' }])
        expect(twoReceived).toEqual([{ type: 'turn_completed', at: 't' }])
    })

    it('routes input messages on a separate channel from events', async () => {
        const events: SessionEvent[] = []
        const inputs: SessionInputMessage[] = []
        await bus.subscribeEvents('s1', (e) => events.push(e))
        await bus.subscribeInput('s1', (m) => inputs.push(m))

        await bus.publishInput('s1', { type: 'user_message', at: 't', content: 'hello' })
        await bus.publishEvent('s1', { type: 'message', at: 't', role: 'assistant', content: 'hi' })

        expect(events).toEqual([{ type: 'message', at: 't', role: 'assistant', content: 'hi' }])
        expect(inputs).toEqual([{ type: 'user_message', at: 't', content: 'hello' }])
    })

    it('supports multiple subscribers per session', async () => {
        const a: SessionEvent[] = []
        const b: SessionEvent[] = []
        await bus.subscribeEvents('s1', (e) => a.push(e))
        await bus.subscribeEvents('s1', (e) => b.push(e))

        await bus.publishEvent('s1', { type: 'turn_started', at: 't' })
        expect(a).toHaveLength(1)
        expect(b).toHaveLength(1)
    })
})
