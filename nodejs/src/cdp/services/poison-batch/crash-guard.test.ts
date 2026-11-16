import { AddressInfo, Server, Socket, connect, createServer } from 'net'
import { CODES, Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { defaultConfig } from '~/common/config/config'
import { RedisV2 } from '~/common/redis/redis-v2'
import { UUIDT } from '~/common/utils/utils'

import {
    CrashGuard,
    CrashGuardSettings,
    SetAside,
    batchAttemptsKey,
    batchSetAsideKey,
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
    const setAside: SetAside = () => Promise.resolve()

    let valkey: RedisV2
    let group: string
    let guard: CrashGuard

    const settings = (
        pool: RedisV2,
        mode: CrashGuardSettings['mode'] = 'shadow',
        maxAttempts = 3
    ): CrashGuardSettings => ({
        valkey: pool,
        mode,
        maxAttempts,
        keyTtlSeconds: 60 * 60,
        maxFlaggedPartitions: 100,
        backgroundTaskTimeoutMs: 10_000,
    })

    const storedKey = (partition: number, start: number) =>
        valkey.useClient({ name: 'test' }, async (client) => ({
            attempts: await client.hget(batchAttemptsKey(group, partition, start), 'attempts'),
            highestOffset: await client.hget(batchAttemptsKey(group, partition, start), 'highest_offset'),
            ttl: await client.ttl(batchAttemptsKey(group, partition, start)),
        }))

    const diverted = (mode = 'shadow') => counter('cdp_batch_diverted_total', { group, mode })

    const crashRepeatedly = async (batch: Message[], times = 3) => {
        for (let i = 0; i < times; i++) {
            await expect(guard.run(batch, crash)).rejects.toThrow('worker crashed')
        }
    }

    beforeAll(() => {
        valkey = createCrashGuardValkeyPool(defaultConfig)
    })

    beforeEach(() => {
        group = `group-${new UUIDT().toString()}`
        guard = new CrashGuard(settings(valkey), group, setAside)
    })

    const poisoned = messages(0, 100, 5)
    const healthy = messages(1, 45, 5)

    it.each([
        ['shadow', [...poisoned, ...healthy], [], null],
        ['enforce', healthy, [poisoned], '3'],
    ] as const)(
        'in %s mode runs or diverts the partition whose batch crashed the configured number of times',
        async (mode, consumed, divertedBatches, storedAttempts) => {
            const produce = jest.fn(setAside)
            guard = new CrashGuard(settings(valkey, mode, 2), group, produce)
            await crashRepeatedly([...poisoned, ...messages(1, 40, 5)], 2)
            expect(await diverted(mode)).toEqual(0)

            const consume = jest.fn(succeed)
            await (
                await guard.run([...poisoned, ...healthy], consume)
            ).backgroundTask

            expect(consume).toHaveBeenCalledWith(consumed)
            expect(produce.mock.calls).toEqual(divertedBatches.map((batch) => [batch]))
            expect(await diverted(mode)).toEqual(1)
            expect((await storedKey(0, 100))!.attempts).toEqual(storedAttempts)
        }
    )

    // A crash in another partition or a rebalance replays the fetch from the same offset, and the replay can hold
    // more messages than the fetch that was set aside.
    it.each([
        ['the same fetch', poisoned, [poisoned]],
        ['a fetch that grew', [...poisoned, ...messages(0, 105, 5)], [poisoned, messages(0, 105, 5)]],
    ])(
        'when %s replays, sets aside only the offsets not set aside yet and consumes none of the flagged partition',
        async (_, replay, divertedBatches) => {
            const produce = jest.fn(setAside)
            guard = new CrashGuard(settings(valkey, 'enforce', 2), group, produce)
            await crashRepeatedly([...poisoned, ...messages(1, 40, 5)], 2)
            const consume = jest.fn(succeed).mockImplementationOnce(crash)

            await expect(guard.run([...poisoned, ...healthy], consume)).rejects.toThrow('worker crashed')
            await (
                await guard.run([...replay, ...healthy], consume)
            ).backgroundTask

            expect(produce.mock.calls).toEqual(divertedBatches.map((batch) => [batch]))
            expect(consume.mock.calls).toEqual([[healthy], [healthy]])
        }
    )

    it('sets aside through the highest offset that crashed when the fetch after a restart is shorter', async () => {
        const produce = jest.fn(setAside)
        guard = new CrashGuard(settings(valkey, 'enforce', 2), group, produce)
        await crashRepeatedly(messages(0, 100, 5), 2)
        const consume = jest.fn(succeed)

        await (
            await guard.run(messages(0, 100, 2), consume)
        ).backgroundTask
        await (
            await guard.run(messages(0, 102, 5), consume)
        ).backgroundTask

        expect(produce.mock.calls).toEqual([[messages(0, 100, 2)], [messages(0, 102, 3)]])
        expect(consume.mock.calls).toEqual([[[]], [messages(0, 105, 2)]])
    })

    it('stops setting aside once more partitions are flagged than the ceiling allows, and keeps the ones it took', async () => {
        const produce = jest.fn(setAside)
        guard = new CrashGuard({ ...settings(valkey, 'enforce', 2), maxFlaggedPartitions: 1 }, group, produce)
        await crashRepeatedly(messages(0, 100, 5), 2)
        await crashRepeatedly(messages(1, 40, 5), 2)
        const consume = jest.fn(succeed)

        await (
            await guard.run(messages(0, 100, 5), consume)
        ).backgroundTask
        await (
            await guard.run(messages(1, 40, 5), consume)
        ).backgroundTask
        await (
            await guard.run(messages(0, 100, 5), consume)
        ).backgroundTask

        expect(produce.mock.calls).toEqual([[messages(0, 100, 5)]])
        expect(consume.mock.calls).toEqual([[[]], [messages(1, 40, 5)], [[]]])
        expect(await counter('cdp_batch_set_aside_ceiling_reached_total', { group, mode: 'enforce' })).toEqual(1)
    })

    it('takes the attempt back once when the background task outlives the guard timeout', async () => {
        guard = new CrashGuard({ ...settings(valkey), backgroundTaskTimeoutMs: 50 }, group, setAside)
        await crashRepeatedly(messages(0, 0, 5), 2)
        let failProduce: (error: Error) => void = () => {}
        const hanging = new Promise<void>((_, reject) => (failProduce = reject))
        const uncounted = () => counter('cdp_batch_attempts_uncounted_total', { group })

        const { backgroundTask } = await guard.run(messages(0, 0, 5), () =>
            Promise.resolve({ backgroundTask: hanging })
        )
        for (let waited = 0; (await uncounted()) === 0 && waited < 2000; waited += 10) {
            await new Promise((resolve) => setTimeout(resolve, 10))
        }
        failProduce(unavailable())
        await expect(backgroundTask).rejects.toThrow('personhog unavailable')

        expect(await uncounted()).toEqual(1)
        expect((await storedKey(0, 0))!.attempts).toEqual('2')
    })

    it.each(['cdp-batch-set-aside-get', 'cdp-batch-set-aside-set'])(
        'sets the flagged partition aside again on a replay when the %s pipeline fails',
        async (failing) => {
            const failingValkey: RedisV2 = {
                ...valkey,
                usePipeline: (options, callback) =>
                    options.name === failing
                        ? Promise.reject(new Error('valkey down'))
                        : valkey.usePipeline(options, callback),
            }
            const produce = jest.fn(setAside)
            guard = new CrashGuard(settings(failingValkey, 'enforce', 2), group, produce)
            await crashRepeatedly([...poisoned, ...messages(1, 40, 5)], 2)
            const consume = jest.fn(succeed).mockImplementationOnce(crash)

            await expect(guard.run([...poisoned, ...healthy], consume)).rejects.toThrow('worker crashed')
            await (
                await guard.run([...poisoned, ...healthy], consume)
            ).backgroundTask

            expect(produce.mock.calls).toEqual([[poisoned], [poisoned]])
            expect(consume.mock.calls).toEqual([[healthy], [healthy]])
        }
    )

    it('keeps the set aside marker as long as the attempts key a replay refreshes', async () => {
        guard = new CrashGuard({ ...settings(valkey, 'enforce', 2), keyTtlSeconds: 5 }, group, setAside)
        await crashRepeatedly([...poisoned, ...messages(1, 40, 5)], 2)
        const consume = jest.fn(succeed).mockImplementationOnce(crash)
        await expect(guard.run([...poisoned, ...healthy], consume)).rejects.toThrow('worker crashed')
        guard = new CrashGuard(settings(valkey, 'enforce', 2), group, setAside)

        await (
            await guard.run([...poisoned, ...healthy], consume)
        ).backgroundTask

        const ttl = await valkey.useClient({ name: 'test' }, (client) => client.ttl(batchSetAsideKey(group, 0, 100)))
        expect(ttl).toBeGreaterThan(5)
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

    const failToPublish = () => Promise.resolve({ backgroundTask: Promise.reject(new Error('produce failed')) })
    const failToSetAside = () => Promise.reject(new Error('produce failed'))
    const unavailable = () => Object.assign(new Error('personhog unavailable'), { isRetriable: true })
    const failOnDependency = () => Promise.reject(unavailable())
    const failOnDependencyInBackground = () => Promise.resolve({ backgroundTask: Promise.reject(unavailable()) })
    const kafkaTimedOut = () =>
        Object.assign(new Error('Local: Message timed out'), { code: CODES.ERRORS.ERR__MSG_TIMED_OUT })
    const failOnKafkaInBackground = () => Promise.resolve({ backgroundTask: Promise.reject(kafkaTimedOut()) })
    const failOnDependencyAfterCorruptingTheKey = async () => {
        await valkey.useClient({ name: 'test' }, (client) =>
            client.hset(batchAttemptsKey(group, 0, 0), 'attempts', 'corrupt')
        )
        throw unavailable()
    }

    it.each([
        ['the background task', 'shadow', failToPublish, setAside, 'background', '4', 0],
        ['the set aside', 'enforce', succeed, failToSetAside, 'run', '4', 0],
        ['a dependency while consuming', 'shadow', failOnDependency, setAside, 'run', '3', 1],
        [
            'a dependency in the background task',
            'enforce',
            failOnDependencyInBackground,
            setAside,
            'background',
            '3',
            1,
        ],
        ['a Kafka delivery in the background task', 'enforce', failOnKafkaInBackground, setAside, 'background', '3', 1],
        [
            'a dependency, and Valkey refuses the take back,',
            'shadow',
            failOnDependencyAfterCorruptingTheKey,
            setAside,
            'run',
            'corrupt',
            0,
        ],
    ] as const)(
        'when %s fails, takes the attempt back only for a dependency error',
        async (_, mode, consume, produce, failsIn, stored, uncounted) => {
            guard = new CrashGuard(settings(valkey, mode), group, produce)
            await crashRepeatedly(messages(0, 0, 5))

            // Consumer v1 commits a batch whose background task rejects, so a failed set aside must reject run itself.
            const tracking = guard.run(messages(0, 0, 5), consume)
            if (failsIn === 'run') {
                await expect(tracking).rejects.toThrow()
            } else {
                await expect((await tracking).backgroundTask).rejects.toThrow()
            }

            expect((await storedKey(0, 0))!.attempts).toEqual(stored)
            expect(await counter('cdp_batch_attempts_uncounted_total', { group })).toEqual(uncounted)
        }
    )

    it('processes the batch when Valkey is unreachable', async () => {
        // Nothing listens on port 1.
        const unreachable = createCrashGuardValkeyPool({ ...defaultConfig, CDP_VALKEY_PORT: 1 })
        const unavailableBefore = await counter('cdp_batch_attempts_marked_total', { group, outcome: 'unavailable' })
        const consume = jest.fn(succeed)

        await (
            await new CrashGuard(settings(unreachable), group, setAside).run(messages(0, 0, 5), consume)
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
        const tracked = new CrashGuard(settings(viaProxy), group, setAside)
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
        const tracked = new CrashGuard(settings(viaProxy), group, setAside)
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
        ['enforce', 'enforce'],
    ] as const)('builds no crash guard unless the mode %p asks for one', (mode, expected) => {
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
        ['CDP_BATCH_QUARANTINE_MAX_FLAGGED_PARTITIONS', 0],
        // The take back after a timeout needs two Valkey timeouts and a margin before the consumer gives up.
        ['CONSUMER_BACKGROUND_TASK_TIMEOUT_MS', 1500],
    ])('refuses %s set to %p', (name, value) => {
        expect(() =>
            createCrashGuardSettings({ ...defaultConfig, CDP_BATCH_QUARANTINE_MODE: 'shadow', [name]: value })
        ).toThrow(name)
    })
})
