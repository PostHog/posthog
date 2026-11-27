import { kafkaProducerMessagesDiscardedCounter } from '~/common/kafka/blackhole-producer'
import { KafkaProducerWrapper } from '~/common/kafka/producer'
import {
    INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP,
    INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP,
} from '~/ingestion/common/outputs/producers'

import { AllowedConfigKey } from './kafka-producer-config'
import { KafkaProducerRegistryBuilder } from './kafka-producer-registry-builder'

jest.mock('~/common/kafka/producer')

describe('KafkaProducerRegistryBuilder', () => {
    beforeEach(() => {
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockReset()
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockImplementation(() =>
            Promise.resolve({
                disconnect: jest.fn().mockResolvedValue(undefined),
            } as unknown as KafkaProducerWrapper)
        )
    })

    const configMap = {
        'metadata.broker.list': 'BROKER_LIST',
        'linger.ms': 'LINGER_MS',
    } as const satisfies Partial<Record<AllowedConfigKey, string>>

    it.each([INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP])(
        'forwards authentication for an application output',
        async (outputMap) => {
            const config = Object.fromEntries(Object.values(outputMap).map((key) => [key, '']))
            config[outputMap['security.protocol']] = 'SASL_PLAINTEXT'
            config[outputMap['sasl.mechanisms']] = 'plain'
            config[outputMap['sasl.username']] = '00123'
            config[outputMap['sasl.password']] = 'false'
            const map: Partial<Record<AllowedConfigKey, string>> = outputMap
            await new KafkaProducerRegistryBuilder(undefined).register('AUTHENTICATED', map).build(config)
            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
                undefined,
                expect.objectContaining({
                    'security.protocol': 'sasl_plaintext',
                    'sasl.mechanisms': 'PLAIN',
                    'sasl.username': '00123',
                    'sasl.password': 'false',
                }),
                'AUTHENTICATED'
            )
        }
    )

    it('creates a registry with a single producer', async () => {
        const config = { BROKER_LIST: 'kafka:9092', LINGER_MS: '20' }

        const registry = await new KafkaProducerRegistryBuilder(undefined).register('DEFAULT', configMap).build(config)

        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(1)
        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
            undefined,
            expect.objectContaining({ 'metadata.broker.list': 'kafka:9092', 'linger.ms': 20 }),
            'DEFAULT'
        )
        expect(registry.getProducer('DEFAULT')).toBeDefined()
    })

    it('creates a registry with multiple producers', async () => {
        const primaryMap = { 'metadata.broker.list': 'PRIMARY_BROKER' } as const satisfies Partial<
            Record<AllowedConfigKey, string>
        >
        const secondaryMap = { 'metadata.broker.list': 'SECONDARY_BROKER' } as const satisfies Partial<
            Record<AllowedConfigKey, string>
        >
        const config = { PRIMARY_BROKER: 'kafka-primary:9092', SECONDARY_BROKER: 'kafka-secondary:9092' }

        const registry = await new KafkaProducerRegistryBuilder(undefined)
            .register('PRIMARY', primaryMap)
            .register('SECONDARY', secondaryMap)
            .build(config)

        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(2)
        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
            undefined,
            expect.objectContaining({ 'metadata.broker.list': 'kafka-primary:9092' }),
            'PRIMARY'
        )
        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
            undefined,
            expect.objectContaining({ 'metadata.broker.list': 'kafka-secondary:9092' }),
            'SECONDARY'
        )
        expect(registry.getProducer('PRIMARY')).toBeDefined()
        expect(registry.getProducer('SECONDARY')).toBeDefined()
        expect(registry.getProducer('PRIMARY')).not.toBe(registry.getProducer('SECONDARY'))
    })

    it('passes kafka client rack to producer creation', async () => {
        const config = { BROKER_LIST: 'kafka:9092', LINGER_MS: '20' }

        await new KafkaProducerRegistryBuilder('us-east-1a').register('DEFAULT', configMap).build(config)

        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith('us-east-1a', expect.any(Object), 'DEFAULT')
    })

    it('skips empty config values and falls back to zod defaults', async () => {
        const config = { BROKER_LIST: '', LINGER_MS: '' }

        await new KafkaProducerRegistryBuilder(undefined).register('DEFAULT', configMap).build(config)

        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
            undefined,
            expect.objectContaining({
                'metadata.broker.list': 'kafka:9092',
                'linger.ms': 20,
            }),
            'DEFAULT'
        )
    })

    it('throws when producer creation fails', async () => {
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockRejectedValue(new Error('connection refused'))
        const config = { BROKER_LIST: 'bad-host:9092', LINGER_MS: '20' }

        await expect(
            new KafkaProducerRegistryBuilder(undefined).register('DEFAULT', configMap).build(config)
        ).rejects.toThrow('connection refused')
    })

    it('registerLazy lets build return only once a slow but healthy broker connects', async () => {
        jest.useFakeTimers()
        try {
            const produce = jest.fn().mockResolvedValue(undefined)
            jest.mocked(KafkaProducerWrapper.createWithConfig).mockImplementation(
                () =>
                    new Promise((resolve) =>
                        setTimeout(() => resolve({ produce } as unknown as KafkaProducerWrapper), 100)
                    )
            )
            const message = { topic: 't', value: Buffer.from('v'), key: null }
            let built = false

            const building = new KafkaProducerRegistryBuilder(undefined)
                .registerLazy('MSK', configMap)
                .build({ BROKER_LIST: 'msk:9094', LINGER_MS: '5' })
                .then((registry) => {
                    built = true
                    return registry
                })
            await jest.advanceTimersByTimeAsync(50)
            expect(built).toBe(false)
            await jest.advanceTimersByTimeAsync(50)

            await (await building).getProducer('MSK').produce(message)
            expect(produce).toHaveBeenCalledWith(message)
        } finally {
            jest.useRealTimers()
        }
    })

    it('registerLazy builds while its broker is down, fails produces fast, and reconnects in the background with backoff', async () => {
        jest.useFakeTimers()
        try {
            const produce = jest.fn().mockResolvedValue(undefined)
            jest.mocked(KafkaProducerWrapper.createWithConfig)
                .mockRejectedValueOnce(new Error('broker transport failure'))
                .mockRejectedValueOnce(new Error('broker transport failure'))
                .mockResolvedValue({ produce } as unknown as KafkaProducerWrapper)
            const message = { topic: 't', value: Buffer.from('v'), key: null }

            const registry = await new KafkaProducerRegistryBuilder(undefined)
                .registerLazy('MSK', configMap)
                .build({ BROKER_LIST: 'msk:9094', LINGER_MS: '5' })
            const msk = registry.getProducer('MSK')

            const refused = { topic: 't', value: Buffer.from('refused'), key: null }

            await expect(msk.produce(refused)).rejects.toThrow('not connected yet')
            await jest.advanceTimersByTimeAsync(5_000)
            expect(jest.mocked(KafkaProducerWrapper.createWithConfig)).toHaveBeenCalledTimes(2)
            await jest.advanceTimersByTimeAsync(9_999)
            expect(jest.mocked(KafkaProducerWrapper.createWithConfig)).toHaveBeenCalledTimes(2)
            await jest.advanceTimersByTimeAsync(1)
            await msk.produce(message)
            expect(produce.mock.calls).toEqual([[message]])
        } finally {
            jest.useRealTimers()
        }
    })

    it('registerLazy stops waiting on a connect that never settles after 5s, and fails its produces and checks in time', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(KafkaProducerWrapper.createWithConfig).mockReturnValue(new Promise(() => {}))
            let built = false

            const building = new KafkaProducerRegistryBuilder(undefined)
                .registerLazy('MSK', configMap)
                .build({ BROKER_LIST: 'msk:9094', LINGER_MS: '5' })
                .then((registry) => {
                    built = true
                    return registry
                })
            await jest.advanceTimersByTimeAsync(4_999)
            expect(built).toBe(false)
            await jest.advanceTimersByTimeAsync(1)

            const message = { topic: 't', value: Buffer.from('v'), key: null }
            await expect((await building).getProducer('MSK').produce(message)).rejects.toThrow('not connected yet')

            const check = (await building).getProducer('MSK').checkTopicExists('t', 1_000)
            const outcome = expect(check).rejects.toThrow('not connected yet')
            await jest.advanceTimersByTimeAsync(1_000)
            await outcome
        } finally {
            jest.useRealTimers()
        }
    })

    it('registerLazy gives a topic check only the time its connect left over', async () => {
        jest.useFakeTimers()
        try {
            const checkTopicExists = jest.fn().mockResolvedValue(undefined)
            jest.mocked(KafkaProducerWrapper.createWithConfig).mockImplementation(
                () =>
                    new Promise((resolve) =>
                        setTimeout(() => resolve({ checkTopicExists } as unknown as KafkaProducerWrapper), 5_900)
                    )
            )
            const building = new KafkaProducerRegistryBuilder(undefined)
                .registerLazy('MSK', configMap)
                .build({ BROKER_LIST: 'msk:9094', LINGER_MS: '5' })
            await jest.advanceTimersByTimeAsync(5_000)
            const msk = (await building).getProducer('MSK')

            const check = msk.checkTopicExists('t', 1_000)
            await jest.advanceTimersByTimeAsync(900)
            await check

            expect(checkTopicExists).toHaveBeenCalledWith('t', 100)
        } finally {
            jest.useRealTimers()
        }
    })

    it('stops a lazy producer from retrying when another producer fails the build', async () => {
        jest.useFakeTimers()
        try {
            jest.mocked(KafkaProducerWrapper.createWithConfig).mockImplementation((_rack, config) =>
                Promise.reject(
                    new Error(config['metadata.broker.list'] === 'bad-host:9092' ? 'eager down' : 'lazy down')
                )
            )

            await expect(
                new KafkaProducerRegistryBuilder(undefined)
                    .register('DEFAULT', configMap)
                    .registerLazy('MSK', { 'metadata.broker.list': 'MSK_BROKER_LIST' } as const)
                    .build({ BROKER_LIST: 'bad-host:9092', LINGER_MS: '20', MSK_BROKER_LIST: 'msk:9094' })
            ).rejects.toThrow('eager down')
            const attempts = jest.mocked(KafkaProducerWrapper.createWithConfig).mock.calls.length
            await jest.advanceTimersByTimeAsync(30_000)

            expect(jest.mocked(KafkaProducerWrapper.createWithConfig).mock.calls.length).toBe(attempts)
        } finally {
            jest.useRealTimers()
        }
    })

    it('buildBlackhole connects to no broker, and its producers discard messages and pass the checks', async () => {
        kafkaProducerMessagesDiscardedCounter.reset()

        const producer = new KafkaProducerRegistryBuilder(undefined)
            .register('DEFAULT', configMap)
            .buildBlackhole()
            .getProducer('DEFAULT')

        await producer.produce({ topic: 'events', key: null, value: Buffer.from('v') })
        await producer.queueMessages({ topic: 'events', messages: [{ value: 'a' }, { value: 'b' }] })

        expect(KafkaProducerWrapper.createWithConfig).not.toHaveBeenCalled()
        await expect(producer.checkConnection()).resolves.toBeUndefined()
        await expect(producer.checkTopicExists('events')).resolves.toBeUndefined()
        expect((await kafkaProducerMessagesDiscardedCounter.get()).values).toEqual([
            expect.objectContaining({ labels: { topic_name: 'events', producer_name: 'DEFAULT' }, value: 3 }),
        ])
    })

    it('registerBlackhole adds a slot that connects to no broker and discards while the others connect', async () => {
        kafkaProducerMessagesDiscardedCounter.reset()
        const config = { BROKER_LIST: 'kafka:9092', LINGER_MS: '20' }

        const registry = await new KafkaProducerRegistryBuilder(undefined)
            .register('DEFAULT', configMap)
            .registerBlackhole('VOID')
            .build(config)
        await registry.getProducer('VOID').produce({ topic: 'events', key: null, value: Buffer.from('v') })

        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(1)
        expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(undefined, expect.any(Object), 'DEFAULT')
        expect((await kafkaProducerMessagesDiscardedCounter.get()).values).toEqual([
            expect.objectContaining({ labels: { topic_name: 'events', producer_name: 'VOID' }, value: 1 }),
        ])
    })

    it('builds an empty registry when no producers are registered', async () => {
        const registry = await new KafkaProducerRegistryBuilder(undefined).build({})

        expect(KafkaProducerWrapper.createWithConfig).not.toHaveBeenCalled()
        await registry.disconnectAll()
    })
})
