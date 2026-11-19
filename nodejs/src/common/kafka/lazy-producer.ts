import { KafkaProducer, ProducerMessage, TopicMessage } from './producer'

const RETRY_AFTER_FAILURE_MS = 5_000

// Connects in the background and fails produces until connected, so a cluster that is down fails the produces that
// pick it rather than the boot of every pod that registers it. A produce never waits on a connect: a message held
// past its caller's deadline could land after the caller already answered that it failed.
export class LazyKafkaProducer implements KafkaProducer {
    private connected?: KafkaProducer
    private connecting?: Promise<KafkaProducer>
    private failedAt = 0
    private closed = false

    constructor(private connect: () => Promise<KafkaProducer>) {
        void this.startConnect()
    }

    private startConnect(): Promise<KafkaProducer> | undefined {
        if (this.closed || this.connecting || Date.now() - this.failedAt < RETRY_AFTER_FAILURE_MS) {
            return this.connecting
        }
        const connecting = this.connect().then(
            (producer) => {
                if (this.closed) {
                    void producer.disconnect().catch(() => undefined)
                } else {
                    this.connected = producer
                }
                return producer
            },
            (error) => {
                this.failedAt = Date.now()
                this.connecting = undefined
                throw error
            }
        )
        connecting.catch(() => undefined)
        this.connecting = connecting
        return connecting
    }

    private ready(): KafkaProducer {
        if (this.connected) {
            return this.connected
        }
        void this.startConnect()
        throw new Error('Kafka producer is not connected yet')
    }

    async produce(message: ProducerMessage): Promise<void> {
        return this.ready().produce(message)
    }

    async queueMessages(topicMessages: TopicMessage | TopicMessage[]): Promise<void> {
        return this.ready().queueMessages(topicMessages)
    }

    async checkConnection(timeoutMs?: number): Promise<void> {
        return (this.connected ?? (await this.startConnect()) ?? this.ready()).checkConnection(timeoutMs)
    }

    async checkTopicExists(topic: string, timeoutMs?: number): Promise<void> {
        return (this.connected ?? (await this.startConnect()) ?? this.ready()).checkTopicExists(topic, timeoutMs)
    }

    async disconnect(): Promise<void> {
        this.closed = true
        const connected = this.connected
        this.connected = undefined
        this.connecting = undefined
        await connected?.disconnect()
    }
}
