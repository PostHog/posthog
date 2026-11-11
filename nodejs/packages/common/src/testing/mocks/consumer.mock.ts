import { KafkaConsumerInterface } from '~/kafka/consumer'

const mockKafkaConsumer = (): jest.Mocked<KafkaConsumerInterface> => ({
    connect: jest.fn().mockResolvedValue(undefined),
    disconnect: jest.fn().mockResolvedValue(undefined),
    isHealthy: jest.fn(),
    offsetsStore: jest.fn(),
    queryWatermarkOffsets: jest.fn().mockResolvedValue([0, 0]),
    committedOffsets: jest.fn().mockResolvedValue([]),
    getPartitionsForTopic: jest.fn().mockResolvedValue([]),
})

// Relative, not aliased: consumers load the compiled helper, and tsc-alias leaves jest.mock specifiers alone.
jest.mock('../../kafka/consumer', () => ({
    createKafkaConsumer: jest.fn(mockKafkaConsumer),
}))
