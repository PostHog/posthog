import { AddressInfo, Server, Socket, connect, createServer } from 'net'
import { Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { UUIDT } from '~/common/utils/utils'

import {
    CrashGuard,
    CrashGuardSettings,
    batchAttemptsKey,
    createCrashGuardSettings,
    createCrashGuardValkeyPool,
    parseCrashGuardMode,
} from './crash-guard'

describe('CrashGuard', () => {
    // The impact dashboard and the shadow rollout read these counters.
    const counter = async (name: string, labels: Record<string, string>): Promise<number> =>
        (await register.getSingleMetric(name)!.get()).values.find((v) =>
            Object.entries(labels).every(([k, value]) => v.labels[k] === value)
        )?.value ?? 0

    const messages = (partition: number, from: number, count: number): Message[] =>
        Array.from({ length: count }, (_, i) => ({
            topic: 'cdp_cyclotron_hog',
            partition,
            offset: from + i,
            value: Buffer.from('{}'),
            size: 2,
        }))

    const crash = () => Promise.reject(new Error('worker crashed'))
    const succeed = () => Promise.resolve({ backgroundTask: Promise.resolve() })

    let valkey: RedisV2
    let group: string
    let guard: CrashGuard

    const shadow = (pool: RedisV2, maxAttempts = 3): CrashGuardSettings => ({
        valkey: pool,
        mode: 'shadow',
        maxAttempts,
        keyTtlSeconds: 60 * 60,
    })

    const storedKey = (partition: number, start: number) =>
        valkey.useClient({ name: 'test' }, async (client) => ({
            attempts: await client.hget(batchAttemptsKey(group, partition, start), 'attempts'),
            highestOffset: await client.hget(batchAttemptsKey(group, partition, start), 'highest_offset'),
            ttl: await client.ttl(batchAttemptsKey(group, partition, start)),
        }))

    const diverted = () => counter('cdp_batch_diverted_total', { group, mode: 'shadow' })

    beforeAll(() => {
        valkey = createCrashGuardValkeyPool(defaultConfig)
    })

    beforeEach(() => {
        group = `group-${new UUIDT().toString()}`
        guard = new CrashGuard(shadow(valkey), group)
    })

    it('flags only the partition whose batch crashed the configured number of times', async () => {
        guard = new CrashGuard(shadow(valkey, 2), group)
        const batch = [...messages(0, 100, 5), ...messages(1, 40, 5)]
        const otherBatch = messages(1, 45, 5)

        for (let i = 0; i < 2; i++) {
            await expect(guard.run(batch, crash)).rejects.toThrow('worker crashed')
        }
        expect(await diverted()).toEqual(0)

        const consume = jest.fn(succeed)
        await (
            await guard.run(messages(0, 100, 5), consume)
        ).backgroundTask
        await (
            await guard.run(otherBatch, succeed)
        ).backgroundTask

        expect(consume).toHaveBeenCalled()
        expect(await diverted()).toEqual(1)
    })

    it('expires a key it never cleared, keeps the highest offset that crashed, and deletes the key once the batch succeeds', async () => {
        await expect(guard.run(messages(3, 0, 5), crash)).rejects.toThrow()
        // A fetch right after a restart can return fewer messages than the fetch that crashed.
        await expect(guard.run(messages(3, 0, 2), crash)).rejects.toThrow()

        const left = await storedKey(3, 0)
        expect(left).toEqual({ attempts: '2', highestOffset: '4', ttl: expect.any(Number) })
        expect(left!.ttl).toBeGreaterThan(0)
        expect(left!.ttl).toBeLessThanOrEqual(60 * 60)

        await (
            await guard.run(messages(3, 0, 5), succeed)
        ).backgroundTask

        expect((await storedKey(3, 0))!.attempts).toBeNull()
    })

    it('keeps counting a batch when the batch before it replays and succeeds', async () => {
        for (let i = 0; i < 2; i++) {
            await (
                await guard.run(messages(0, 0, 5), succeed)
            ).backgroundTask
            await expect(guard.run(messages(0, 5, 5), crash)).rejects.toThrow()
        }
        await (
            await guard.run(messages(0, 0, 5), succeed)
        ).backgroundTask
        await expect(guard.run(messages(0, 5, 5), crash)).rejects.toThrow()

        await (
            await guard.run(messages(0, 5, 5), succeed)
        ).backgroundTask

        expect(await diverted()).toEqual(1)
    })

    it('does not clear the mark when the background task fails', async () => {
        const result = await guard.run(messages(0, 0, 5), () =>
            Promise.resolve({ backgroundTask: Promise.reject(new Error('produce failed')) })
        )
        await expect(result.backgroundTask).rejects.toThrow('produce failed')

        expect((await storedKey(0, 0))!.attempts).toEqual('1')
    })

    it('processes the batch when Valkey is unreachable', async () => {
        // Nothing listens on port 1.
        const unreachable = createCrashGuardValkeyPool({ ...defaultConfig, CDP_VALKEY_PORT: 1 })
        const unavailableBefore = await counter('cdp_batch_attempts_marked_total', { group, outcome: 'unavailable' })
        const consume = jest.fn(succeed)

        await (
            await new CrashGuard(shadow(unreachable), group).run(messages(0, 0, 5), consume)
        ).backgroundTask

        expect(consume).toHaveBeenCalled()
        expect(await counter('cdp_batch_attempts_marked_total', { group, outcome: 'unavailable' })).toEqual(
            unavailableBefore + 1
        )
    })

    it('processes the batch when the Valkey connection drops after it was established', async () => {
        // A proxy stands in for Valkey, so the test can cut a connection the pool already holds.
        const sockets: Socket[] = []
        const proxy: Server = createServer((client) => {
            const upstream = connect(defaultConfig.CDP_VALKEY_PORT, '127.0.0.1')
            sockets.push(client, upstream)
            client.pipe(upstream).pipe(client)
            client.on('error', () => {})
            upstream.on('error', () => {})
        })
        await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve))
        const viaProxy = createCrashGuardValkeyPool({
            ...defaultConfig,
            CDP_VALKEY_PORT: (proxy.address() as AddressInfo).port,
        })
        const tracked = new CrashGuard(shadow(viaProxy), group)
        await (
            await tracked.run(messages(0, 0, 5), succeed)
        ).backgroundTask

        proxy.close()
        sockets.forEach((socket) => socket.destroy())
        const unavailableBefore = await counter('cdp_batch_attempts_marked_total', { group, outcome: 'unavailable' })
        const consume = jest.fn(succeed)
        await (
            await tracked.run(messages(0, 5, 5), consume)
        ).backgroundTask

        expect(consume).toHaveBeenCalled()
        expect(await counter('cdp_batch_attempts_marked_total', { group, outcome: 'unavailable' })).toEqual(
            unavailableBefore + 1
        )
    })

    it('counts on a fresh connection after an established one stops answering', async () => {
        // The proxy silences the connections the pool already holds, while new connections still work.
        const clients: Socket[] = []
        const sockets: Socket[] = []
        const silenced = new Set<Socket>()
        const proxy: Server = createServer((client) => {
            const upstream = connect(defaultConfig.CDP_VALKEY_PORT, '127.0.0.1')
            clients.push(client)
            sockets.push(client, upstream)
            client.pipe(upstream)
            upstream.on('data', (chunk) => {
                if (!silenced.has(client)) {
                    client.write(chunk)
                }
            })
            client.on('error', () => {})
            upstream.on('error', () => {})
        })
        await new Promise<void>((resolve) => proxy.listen(0, '127.0.0.1', resolve))
        const viaProxy = createCrashGuardValkeyPool({
            ...defaultConfig,
            CDP_VALKEY_PORT: (proxy.address() as AddressInfo).port,
        })
        const tracked = new CrashGuard(shadow(viaProxy), group)
        const unavailable = () => counter('cdp_batch_attempts_marked_total', { group, outcome: 'unavailable' })

        try {
            await (
                await tracked.run(messages(0, 0, 5), succeed)
            ).backgroundTask
            clients.forEach((client) => silenced.add(client))
            await (
                await tracked.run(messages(0, 5, 5), succeed)
            ).backgroundTask
            const unavailableAfterSilence = await unavailable()
            expect(unavailableAfterSilence).toEqual(1)

            await (
                await tracked.run(messages(0, 10, 5), succeed)
            ).backgroundTask

            expect(await unavailable()).toEqual(unavailableAfterSilence)
        } finally {
            proxy.close()
            sockets.forEach((socket) => socket.destroy())
        }
    })

    it.each([
        ['off', null],
        ['shadow', 'shadow'],
        [' Shadow ', 'shadow'],
    ])('builds no crash guard unless the mode %p asks for one', (mode, expected) => {
        expect(createCrashGuardSettings({ ...defaultConfig, CDP_BATCH_QUARANTINE_MODE: mode })?.mode ?? null).toEqual(
            expected
        )
    })

    it.each(['bogus', 'shdow', ''])('refuses the unknown quarantine mode %p', (mode) => {
        expect(() => parseCrashGuardMode(mode)).toThrow('CDP_BATCH_QUARANTINE_MODE')
    })

    it.each([
        ['CDP_BATCH_QUARANTINE_MAX_ATTEMPTS', 0],
        ['CDP_BATCH_QUARANTINE_KEY_TTL_SECONDS', NaN],
        ['CDP_BATCH_QUARANTINE_VALKEY_TIMEOUT_MS', 2.5],
    ])('refuses %s set to %p', (name, value) => {
        expect(() =>
            createCrashGuardSettings({ ...defaultConfig, CDP_BATCH_QUARANTINE_MODE: 'shadow', [name]: value })
        ).toThrow(name)
    })
})
