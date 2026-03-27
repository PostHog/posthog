import { KafkaProducerWrapper } from '../../kafka/producer'
import { AllowedConfigKey } from './kafka-producer-config'
import { KafkaProducerRegistry } from './kafka-producer-registry'

jest.mock('../../kafka/producer')

type TestProducer = 'ALPHA' | 'BETA'

const TEST_CONFIG_MAP: Record<TestProducer, Partial<Record<AllowedConfigKey, string>>> = {
    ALPHA: {
        'metadata.broker.list': 'TEST_ALPHA_BROKER',
    },
    BETA: {
        'metadata.broker.list': 'TEST_BETA_BROKER',
    },
}

describe('KafkaProducerRegistry', () => {
    const OLD_ENV = process.env

    beforeEach(() => {
        jest.resetModules()
        process.env = { ...OLD_ENV }
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockReset()
    })

    afterAll(() => {
        process.env = OLD_ENV
    })

    function mockCreateWithConfig(): void {
        const mockProducer = { disconnect: jest.fn().mockResolvedValue(undefined) } as unknown as KafkaProducerWrapper
        jest.mocked(KafkaProducerWrapper.createWithConfig).mockResolvedValue(mockProducer)
    }

    function createRegistry(): KafkaProducerRegistry<TestProducer> {
        return new KafkaProducerRegistry('rack1', TEST_CONFIG_MAP)
    }

    describe('getProducer', () => {
        it('creates a producer with config from env vars', async () => {
            process.env.TEST_ALPHA_BROKER = 'alpha:9092'
            mockCreateWithConfig()

            const registry = createRegistry()
            await registry.getProducer('ALPHA')

            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(1)
            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledWith(
                'rack1',
                expect.objectContaining({ 'metadata.broker.list': 'alpha:9092' })
            )
        })

        it('returns the same producer on concurrent calls (singleton, no race condition)', async () => {
            mockCreateWithConfig()

            const registry = createRegistry()
            const [first, second] = await Promise.all([registry.getProducer('ALPHA'), registry.getProducer('ALPHA')])

            expect(first).toBe(second)
            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(1)
        })

        it('creates separate producers for different names', async () => {
            mockCreateWithConfig()

            const registry = createRegistry()
            await registry.getProducer('ALPHA')
            await registry.getProducer('BETA')

            expect(KafkaProducerWrapper.createWithConfig).toHaveBeenCalledTimes(2)
        })
    })

    describe('disconnectAll', () => {
        it('disconnects all producers', async () => {
            const disconnect = jest.fn().mockResolvedValue(undefined)
            jest.mocked(KafkaProducerWrapper.createWithConfig).mockResolvedValue({
                disconnect,
            } as unknown as KafkaProducerWrapper)

            const registry = createRegistry()
            await registry.getProducer('ALPHA')
            await registry.getProducer('BETA')

            await registry.disconnectAll()

            expect(disconnect).toHaveBeenCalledTimes(2)
        })

        it('continues disconnecting remaining producers when one fails', async () => {
            let callCount = 0
            const disconnect = jest.fn().mockImplementation(async () => {
                callCount++
                if (callCount === 1) {
                    throw new Error('flush timeout')
                }
                return Promise.resolve()
            })

            jest.mocked(KafkaProducerWrapper.createWithConfig).mockResolvedValue({
                disconnect,
            } as unknown as KafkaProducerWrapper)

            const registry = createRegistry()
            await registry.getProducer('ALPHA')
            await registry.getProducer('BETA')

            await expect(registry.disconnectAll()).rejects.toThrow('Failed to disconnect producers')

            expect(disconnect).toHaveBeenCalledTimes(2)
        })
    })
})
