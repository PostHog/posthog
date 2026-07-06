/**
 * RedisSessionEventBus integration test.
 *
 * Skips when no Redis is reachable at REDIS_URL (default local Redis URL)
 * — vitest in CI without redis just no-ops the suite. When reachable, this is
 * a real round-trip: two bus instances (publisher + subscriber), each with
 * their own pub/sub pair to redis, prove cross-process semantics in-process.
 */

import { RedisSessionEventBus, SessionEvent } from './bus'

// nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
const REDIS_URL = process.env.REDIS_URL ?? 'redis://localhost:6379'

async function isReachable(): Promise<boolean> {
    try {
        const mod = await import('ioredis')
        const Ctor = (mod as { default?: typeof import('ioredis').default }).default ?? mod
        const RedisCtor = Ctor as unknown as new (
            url: string,
            opts?: { lazyConnect?: boolean; maxRetriesPerRequest?: number }
        ) => {
            connect: () => Promise<void>
            disconnect: () => void
        }
        const probe = new RedisCtor(REDIS_URL, { lazyConnect: true, maxRetriesPerRequest: 0 })
        try {
            await probe.connect()
            return true
        } finally {
            probe.disconnect()
        }
    } catch {
        return false
    }
}

let reachable = false

const maybeDescribe = process.env.SKIP_REDIS_TESTS === '1' ? describe.skip : describe

maybeDescribe('RedisSessionEventBus', () => {
    beforeAll(async () => {
        reachable = await isReachable()
        if (!reachable) {
            // eslint-disable-next-line no-console
            console.warn(`[bus.test] redis at ${REDIS_URL} unreachable — skipping suite`)
        }
    })

    function mkEvent(sessionId: string, kind: SessionEvent['kind'] = 'session_started'): SessionEvent {
        return { session_id: sessionId, kind, data: { hello: 'world' }, ts: new Date().toISOString() }
    }

    it('delivers an event from one bus instance to another', async () => {
        if (!reachable) {
            return
        }
        const prefix = `test_${Date.now()}`
        const pub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        const sub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        await pub.connect()
        await sub.connect()

        const received: SessionEvent[] = []
        sub.subscribe('s1', (e) => received.push(e))
        // ioredis SUBSCRIBE round-trip — give it a moment to register before publishing.
        await new Promise((r) => setTimeout(r, 50))

        await pub.publish(mkEvent('s1', 'completed'))
        // Round-trip via redis broker — short wait.
        await new Promise((r) => setTimeout(r, 50))

        expect(received).toHaveLength(1)
        expect(received[0]).toMatchObject({ session_id: 's1', kind: 'completed' })

        await pub.disconnect()
        await sub.disconnect()
    })

    it('whenSubscribed() resolves only once the channel is live — no sleep needed before publish', async () => {
        if (!reachable) {
            return
        }
        // The other cases sleep 50ms after subscribe() to let the fire-and-forget
        // SUBSCRIBE ACK land. whenSubscribed() replaces that race with a deterministic
        // wait: awaiting it, then publishing immediately (no sleep), still delivers.
        const prefix = `test_ready_${Date.now()}`
        const pub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        const sub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        await pub.connect()
        await sub.connect()

        const received: SessionEvent[] = []
        sub.subscribe('r1', (e) => received.push(e))
        await sub.whenSubscribed('r1')

        await pub.publish(mkEvent('r1', 'completed'))
        // Only the broker round-trip needs a beat now; the SUBSCRIBE is already ACKed.
        await new Promise((r) => setTimeout(r, 50))

        expect(received).toHaveLength(1)
        expect(received[0]).toMatchObject({ session_id: 'r1', kind: 'completed' })

        await pub.disconnect()
        await sub.disconnect()
    })

    it('does not deliver events for other session ids', async () => {
        if (!reachable) {
            return
        }
        const prefix = `test_iso_${Date.now()}`
        const pub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        const sub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        await pub.connect()
        await sub.connect()

        const aReceived: SessionEvent[] = []
        sub.subscribe('a', (e) => aReceived.push(e))
        await new Promise((r) => setTimeout(r, 50))

        await pub.publish(mkEvent('b', 'session_started'))
        await pub.publish(mkEvent('a', 'session_started'))
        await new Promise((r) => setTimeout(r, 50))

        expect(aReceived).toHaveLength(1)
        expect(aReceived[0].session_id).toBe('a')

        await pub.disconnect()
        await sub.disconnect()
    })

    it('unsubscribe() stops further delivery to that listener', async () => {
        if (!reachable) {
            return
        }
        const prefix = `test_unsub_${Date.now()}`
        const pub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        const sub = new RedisSessionEventBus({ url: REDIS_URL, channelPrefix: prefix })
        await pub.connect()
        await sub.connect()

        const received: SessionEvent[] = []
        const unsub = sub.subscribe('x', (e) => received.push(e))
        await new Promise((r) => setTimeout(r, 50))

        await pub.publish(mkEvent('x'))
        await new Promise((r) => setTimeout(r, 50))
        expect(received).toHaveLength(1)

        unsub()
        await new Promise((r) => setTimeout(r, 50))
        await pub.publish(mkEvent('x'))
        await new Promise((r) => setTimeout(r, 50))
        expect(received).toHaveLength(1)

        await pub.disconnect()
        await sub.disconnect()
    })
})
