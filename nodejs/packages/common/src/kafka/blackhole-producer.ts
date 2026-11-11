import { Counter } from 'prom-client'

import { KafkaProducer, ProducerMessage, TopicMessage } from './producer'

export const kafkaProducerMessagesDiscardedCounter = new Counter({
    name: 'kafka_producer_messages_discarded_total',
    help: 'Count of messages a blackhole producer discarded instead of writing to Kafka, by destination topic.',
    labelNames: ['topic_name', 'producer_name'],
})

export class BlackholeKafkaProducer implements KafkaProducer {
    constructor(readonly name: string) {}

    produce({ topic }: ProducerMessage): Promise<void> {
        kafkaProducerMessagesDiscardedCounter.inc({ topic_name: topic, producer_name: this.name })
        return Promise.resolve()
    }

    queueMessages(topicMessages: TopicMessage | TopicMessage[]): Promise<void> {
        for (const { topic, messages } of Array.isArray(topicMessages) ? topicMessages : [topicMessages]) {
            kafkaProducerMessagesDiscardedCounter.inc({ topic_name: topic, producer_name: this.name }, messages.length)
        }
        return Promise.resolve()
    }

    disconnect(): Promise<void> {
        return Promise.resolve()
    }

    checkConnection(): Promise<void> {
        return Promise.resolve()
    }

    checkTopicExists(): Promise<void> {
        return Promise.resolve()
    }
}
