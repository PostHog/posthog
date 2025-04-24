import { KafkaProducerWrapper, TopicMessage } from '../../../src/kafka/producer'
import { parseJSON } from '../../../src/utils/json-parse'

export type ParsedTopicMessage = {
    topic: string
    messages: {
        key: string | null
        value: Record<string, any> | null
        headers?: Record<string, string>
    }[]
}

export type DecodedKafkaMessage = {
    topic: string
    key?: any
    value: Record<string, unknown>
    headers?: Record<string, string>
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

export const getProducedMessages = (): TopicMessage[] => {
    return jest.mocked(mockProducer).produce.mock.calls.reduce((acc, call) => {
        const headers = call[0].headers?.reduce<Record<string, string | Buffer>>((acc, header) => {
            acc[Object.keys(header)[0]] = Object.values(header)[0]
            return acc
        }, {})

        const message: TopicMessage['messages'][number] = {
            key: call[0].key,
            value: call[0].value,
        }

        if (headers) {
            message.headers = headers
        }

        return acc.concat([
            {
                topic: call[0].topic,
                messages: [message],
            },
        ])
    }, [] as TopicMessage[])
}

export const getParsedQueuedMessages = (): ParsedTopicMessage[] => {
    const allMessages = getProducedMessages().concat(getQueuedMessages())
    return allMessages.map((topicMessage) => ({
        topic: topicMessage.topic,
        messages: topicMessage.messages.map((message) => ({
            key: typeof message.key === 'string' ? message.key : null,
            value: message.value ? parseJSON(message.value.toString()) : null,
            headers: message.headers,
        })),
    }))
}

export const getProducedKafkaMessages = (): DecodedKafkaMessage[] => {
    const queuedMessages = getParsedQueuedMessages()

    const result: DecodedKafkaMessage[] = []

    for (const topicMessage of queuedMessages) {
        for (const message of topicMessage.messages) {
            result.push({
                topic: topicMessage.topic,
                key: message.key,
                value: message.value ?? {},
                headers: message.headers,
            })
        }
    }

    return result
}

export const getProducedKafkaMessagesWithHeaders = (): DecodedKafkaMessage[] => {
    const queuedMessages = getParsedQueuedMessages()

    const result: DecodedKafkaMessage[] = []

    for (const topicMessage of queuedMessages) {
        for (const message of topicMessage.messages) {
            result.push({
                topic: topicMessage.topic,
                key: message.key,
                value: message.value ?? {},
                headers: message.headers,
            })
        }
    }

    return result
}

export const getProducedKafkaMessagesForTopic = (topic: string): DecodedKafkaMessage[] => {
    return getProducedKafkaMessages().filter((x) => x.topic === topic)
}
