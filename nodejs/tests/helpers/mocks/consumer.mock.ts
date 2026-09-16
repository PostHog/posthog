import { KafkaConsumerInterface } from '~/common/kafka/consumer'

const mockKafkaConsumer = (): jest.Mocked<KafkaConsumerInterface> => ({
    connect: jest.fn().mockResolvedValue(undefined),
    disconnect: jest.fn().mockResolvedValue(undefined),
    isHealthy: jest.fn(),
    offsetsStore: jest.fn(),
    queryWatermarkOffsets: jest.fn().mockResolvedValue([0, 0]),
    committedOffsets: jest.fn().mockResolvedValue([]),
    getPartitionsForTopic: jest.fn().mockResolvedValue([]),
})

jest.mock('~/common/kafka/consumer', () => ({
    createKafkaConsumer: jest.fn(mockKafkaConsumer),
}))
