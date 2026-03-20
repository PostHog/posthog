import { KafkaProducerWrapper } from '../../kafka/producer'
import { KafkaProducerRegistry } from './producer-registry'

jest.mock('../../kafka/producer')

describe('KafkaProducerRegistry', () => {
    const OLD_ENV = process.env

    beforeEach(() => {
        jest.resetModules()
        process.env = { ...OLD_ENV }
        jest.mocked(KafkaProducerWrapper.create).mockReset()
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockReset()
    })

    afterAll(() => {
        process.env = OLD_ENV
    })

    function setupProducerEnv(name: string): void {
        process.env[`INGESTION_KAFKA_PRODUCER_${name}_METADATA_BROKER_LIST`] = 'broker:9092'
    }

    function mockCreate(): void {
        const mockProducer = { disconnect: jest.fn().mockResolvedValue(undefined) } as unknown as KafkaProducerWrapper
        jest.mocked(KafkaProducerWrapper.create).mockResolvedValue(mockProducer)
    }

    function mockCreateWithConfig(): void {
        const mockProducer = { disconnect: jest.fn().mockResolvedValue(undefined) } as unknown as KafkaProducerWrapper
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockResolvedValue(mockProducer)
    }

    describe('default producer (name=undefined)', () => {
        it('uses KafkaProducerWrapper.create with PRODUCER mode', async () => {
            mockCreate()
            const registry = new KafkaProducerRegistry('rack1')

            await registry.getProducer(undefined)

            expect(KafkaProducerWrapper.create).toHaveBeenCalledWith('rack1', 'PRODUCER')
            expect(KafkaProducerWrapper.createWithConfig).not.toHaveBeenCalled()
        })

        it('is a singleton', async () => {
            mockCreate()
            const registry = new KafkaProducerRegistry('rack1')

            const first = await registry.getProducer(undefined)
            const second = await registry.getProducer(undefined)

            expect(first).toBe(second)
            expect(KafkaProducerWrapper.create).toHaveBeenCalledTimes(1)
        })
    })

    describe('named producers', () => {
        it('creates a producer with config from env vars', async () => {
            setupProducerEnv('MSK')
            mockCreateWithConfig()
            const registry = new KafkaProducerRegistry('rack1')

            await registry.getProducer('MSK')

            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
                'rack1',
                expect.objectContaining({ 'metadata.broker.list': 'broker:9092' })
            )
        })

        it('returns the same producer on subsequent calls (singleton)', async () => {
            setupProducerEnv('MSK')
            mockCreateWithConfig()
            const registry = new KafkaProducerRegistry('rack1')

            const first = await registry.getProducer('MSK')
            const second = await registry.getProducer('MSK')

            expect(first).toBe(second)
            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(1)
        })

        it('normalizes name to uppercase', async () => {
            setupProducerEnv('MSK')
            mockCreateWithConfig()
            const registry = new KafkaProducerRegistry(undefined)

            const lower = await registry.getProducer('msk')
            const upper = await registry.getProducer('MSK')

            expect(lower).toBe(upper)
            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(1)
        })

        it('throws when no env vars are configured for the name', async () => {
            const registry = new KafkaProducerRegistry(undefined)

            await expect(registry.getProducer('MISSING')).rejects.toThrow(
                'No INGESTION_KAFKA_PRODUCER_MISSING_* env vars found'
            )
        })
    })

    describe('disconnectAll', () => {
        it('disconnects all producers', async () => {
            setupProducerEnv('CUSTOM')
            const disconnectDefault = jest.fn().mockResolvedValue(undefined)
            const disconnectCustom = jest.fn().mockResolvedValue(undefined)

            jest.mocked(KafkaProducerWrapper.create).mockResolvedValueOnce({
                disconnect: disconnectDefault,
            } as unknown as KafkaProducerWrapper)
            jest.mocked(KafkaProducerWrapper.createWithConfig).mockResolvedValueOnce({
                disconnect: disconnectCustom,
            } as unknown as KafkaProducerWrapper)

            const registry = new KafkaProducerRegistry(undefined)
            await registry.getProducer(undefined)
            await registry.getProducer('CUSTOM')

            await registry.disconnectAll()

            expect(disconnectDefault).toHaveBeenCalledTimes(1)
            expect(disconnectCustom).toHaveBeenCalledTimes(1)
        })
    })
})
