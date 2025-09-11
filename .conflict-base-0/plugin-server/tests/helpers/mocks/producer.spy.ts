/**
 * NOTE: This class has helpers for observing a kafka producer which is useful for validating
 * messages are created as expected.
 *
 * It does not mock the producer itself, for that see `producer.mock.ts`
 */
import { uncompressSync } from 'snappy'

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

const tryDecompress = (value: string | Buffer): string => {
    try {
        return uncompressSync(value).toString()
    } catch (error) {
        return value.toString()
    }
}

export class KafkaProducerObserver {
    public readonly produceSpy: jest.SpyInstance<
        Promise<void>,
        Parameters<typeof KafkaProducerWrapper.prototype.produce>
    >

    constructor(private producer: KafkaProducerWrapper) {
        // Spy on the methods we need
        this.produceSpy = jest.spyOn(producer, 'produce')
    }

    public getProducedMessages() {
        return this.produceSpy.mock.calls.reduce((acc, call) => {
            return acc.concat([
                {
                    topic: call[0].topic,
                    messages: [
                        {
                            key: call[0].key,
                            value: call[0].value,
                            headers: call[0].headers,
                        },
                    ],
                },
            ])
        }, [] as TopicMessage[])
    }

    public getParsedQueuedMessages(): ParsedTopicMessage[] {
        const allMessages = this.getProducedMessages()
        return allMessages.map((topicMessage) => ({
            topic: topicMessage.topic,
            messages: topicMessage.messages.map((message) => ({
                key: message.key?.toString() ?? null,
                value: message.value ? parseJSON(tryDecompress(message.value)) : null,
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

    public getProducedKafkaMessagesForTopic(topic: string): DecodedKafkaMessage[] {
        return this.getProducedKafkaMessages().filter((x) => x.topic === topic)
    }

    public resetKafkaProducer() {
        this.produceSpy.mockClear()
    }
}
