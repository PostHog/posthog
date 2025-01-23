import { KafkaProducerWrapper, TopicMessage } from '../../../src/kafka/producer'

export type ParsedTopicMessage = {
    topic: string
    messages: {
        key: string | null
        value: Record<string, any> | null
    }[]
}

jest.mock('../../../src/kafka/producer', () => {
    const mockKafkaProducer: jest.Mocked<KafkaProducerWrapper> = {
        producer: {
            connect: jest.fn(),
        } as any,
        disconnect: jest.fn(),
        produce: jest.fn().mockReturnValue(Promise.resolve()),
        queueMessages: jest.fn().mockReturnValue(Promise.resolve()),
        flush: jest.fn().mockReturnValue(Promise.resolve()),
    }

    const MockKafkaProducer = {
        create: jest.fn(() => Promise.resolve(mockKafkaProducer)),
    }
    return {
        KafkaProducerWrapper: MockKafkaProducer,
        _producer: mockKafkaProducer,
    }
})

export const mockProducer = require('../../../src/kafka/producer')._producer as KafkaProducerWrapper

export const getQueuedMessages = (): TopicMessage[] => {
    return jest.mocked(mockProducer).queueMessages.mock.calls.reduce((acc, call) => {
        return acc.concat(Array.isArray(call[0]) ? call[0] : [call[0]])
    }, [] as TopicMessage[])
}

export const getParsedQueuedMessages = (): ParsedTopicMessage[] => {
    return getQueuedMessages().map((topicMessage) => ({
        topic: topicMessage.topic,
        messages: topicMessage.messages.map((message) => ({
            key: typeof message.key === 'string' ? message.key : null,
            value: message.value ? JSON.parse(message.value.toString()) : null,
        })),
    }))
}
