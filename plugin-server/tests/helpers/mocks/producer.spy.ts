/**
 * NOTE: This class has helpers for observing a kafka producer which is useful for validating
 * messages are created as expected.
 *
 * It does not mock the producer itself, for that see `producer.mock.ts`
 */

import { KafkaProducerWrapper, TopicMessage } from '../../../src/kafka/producer'
import { parseJSON } from '../../../src/utils/json-parse'

export type ParsedTopicMessage = {
    topic: TopicMessage['topic']
    messages: {
        key: TopicMessage['messages'][number]['key']
        value: Record<string, any> | null
        headers?: TopicMessage['messages'][number]['headers']
    }[]
}

export type DecodedKafkaMessage = {
    topic: TopicMessage['topic']
    key?: TopicMessage['messages'][number]['key']
    value: Record<string, unknown>
    headers?: TopicMessage['messages'][number]['headers']
}

export class KafkaProducerObserver {
    public readonly queueMessagesSpy: jest.SpyInstance<
        Promise<void>,
        Parameters<typeof KafkaProducerWrapper.prototype.queueMessages>
    >
    public readonly produceSpy: jest.SpyInstance<
        Promise<void>,
        Parameters<typeof KafkaProducerWrapper.prototype.produce>
    >

    constructor(private producer: KafkaProducerWrapper) {
        // Spy on the methods we need
        this.queueMessagesSpy = jest.spyOn(producer, 'queueMessages')
        this.produceSpy = jest.spyOn(producer, 'produce')
    }

    public getQueuedMessages() {
        return this.queueMessagesSpy.mock.calls.reduce((acc, call) => {
            return acc.concat(Array.isArray(call[0]) ? call[0] : [call[0]])
        }, [] as TopicMessage[])
    }

    public getProducedMessages() {
        return this.produceSpy.mock.calls.reduce((acc, call) => {
            const headers = call[0].headers?.reduce<Record<string, string>>((acc, header) => {
                const key = Object.keys(header)[0]
                const value = header[key]
                acc[key] = value.toString()
                return acc
            }, {})

            return acc.concat([
                {
                    topic: call[0].topic,
                    messages: [
                        {
                            key: call[0].key,
                            value: call[0].value,
                            headers: headers,
                        },
                    ],
                },
            ])
        }, [] as TopicMessage[])
    }

    public getParsedQueuedMessages(): ParsedTopicMessage[] {
        const allMessages = this.getProducedMessages().concat(this.getQueuedMessages())
        return allMessages.map((topicMessage) => ({
            topic: topicMessage.topic,
            messages: topicMessage.messages.map((message) => ({
                key: typeof message.key === 'string' ? message.key : null,
                value: message.value ? parseJSON(message.value.toString()) : null,
                headers: message.headers,
            })),
        }))
    }

    public getProducedKafkaMessages(): DecodedKafkaMessage[] {
        const queuedMessages = this.getParsedQueuedMessages()

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

    public getProducedKafkaMessagesWithHeaders(): DecodedKafkaMessage[] {
        const queuedMessages = this.getParsedQueuedMessages()

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

    public getProducedKafkaMessagesForTopic(topic: string): DecodedKafkaMessage[] {
        return this.getProducedKafkaMessages().filter((x) => x.topic === topic)
    }

    public resetKafkaProducer() {
        this.queueMessagesSpy.mockClear()
        this.produceSpy.mockClear()
    }
}
