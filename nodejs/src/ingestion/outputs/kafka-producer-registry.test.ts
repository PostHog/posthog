import { KafkaProducerWrapper } from '../../kafka/producer'
import { KafkaProducerRegistry } from './kafka-producer-registry'

type TestProducer = 'ALPHA' | 'BETA'

function createMockProducer(): KafkaProducerWrapper {
    return {
        disconnect: jest.fn().mockResolvedValue(undefined),
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: jest.fn().mockResolvedValue(undefined),
    } as unknown as KafkaProducerWrapper
}

function createRegistry(): KafkaProducerRegistry<TestProducer> {
    const producers: Record<TestProducer, KafkaProducerWrapper> = {
        ALPHA: createMockProducer(),
        BETA: createMockProducer(),
    }
    return new KafkaProducerRegistry(producers)
}

describe('KafkaProducerRegistry', () => {
    describe('getProducer', () => {
        it('returns the registered producer by name', () => {
            const registry = createRegistry()
            const producer = registry.getProducer('ALPHA')
            expect(producer).toBeDefined()
        })

        it('returns different producers for different names', () => {
            const registry = createRegistry()
            const alpha = registry.getProducer('ALPHA')
            const beta = registry.getProducer('BETA')
            expect(alpha).not.toBe(beta)
        })
    })

    describe('disconnectAll', () => {
        it('disconnects all producers', async () => {
            const registry = createRegistry()
            const alpha = registry.getProducer('ALPHA')
            const beta = registry.getProducer('BETA')

            await registry.disconnectAll()

            expect(alpha.disconnect).toHaveBeenCalledTimes(1)
            expect(beta.disconnect).toHaveBeenCalledTimes(1)
        })

        it('continues disconnecting remaining producers when one fails', async () => {
            const registry = createRegistry()
            const alpha = registry.getProducer('ALPHA')
            const beta = registry.getProducer('BETA')

            jest.mocked(alpha.disconnect).mockRejectedValue(new Error('flush timeout'))

            await expect(registry.disconnectAll()).rejects.toThrow('Failed to disconnect producers')
            expect(beta.disconnect).toHaveBeenCalledTimes(1)
        })
    })
})
