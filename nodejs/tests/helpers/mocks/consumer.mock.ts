import { KafkaConsumerInterface } from '~/common/kafka/consumer'

const mockKafkaConsumer = (): jest.Mocked<KafkaConsumerInterface> => ({
    connect: jest.fn().mockResolvedValue(undefined),
    disconnect: jest.fn().mockResolvedValue(undefined),
    isHealthy: jest.fn(),
    offsetsStore: jest.fn(),
})

jest.mock('~/common/kafka/consumer', () => ({
    createKafkaConsumer: jest.fn(mockKafkaConsumer),
}))
