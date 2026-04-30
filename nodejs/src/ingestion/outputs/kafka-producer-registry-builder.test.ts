import { KafkaProducerWrapper } from '../../kafka/producer'
import { AllowedConfigKey } from './kafka-producer-config'
import { KafkaProducerRegistryBuilder } from './kafka-producer-registry-builder'

jest.mock('../../kafka/producer')

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

    it('builds an empty registry when no producers are registered', async () => {
        const registry = await new KafkaProducerRegistryBuilder(undefined).build({})

        expect(KafkaProducerWrapper.createWithConfig).not.toHaveBeenCalled()
        await registry.disconnectAll()
    })
})
