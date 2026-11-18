import { KafkaProducer, ProducerMessage, TopicMessage } from './producer'

// Connects on first use and again after a failed connect, so a cluster that is down at startup fails the produces
// that pick it rather than the boot of every pod that registers it.
export class LazyKafkaProducer implements KafkaProducer {
    private connecting?: Promise<KafkaProducer>

    constructor(private connect: () => Promise<KafkaProducer>) {
        this.producer().catch(() => undefined)
    }

    private producer(): Promise<KafkaProducer> {
        this.connecting ??= this.connect().catch((error) => {
            this.connecting = undefined
            throw error
        })
        return this.connecting
    }

    async produce(message: ProducerMessage): Promise<void> {
        return (await this.producer()).produce(message)
    }

    async queueMessages(topicMessages: TopicMessage | TopicMessage[]): Promise<void> {
        return (await this.producer()).queueMessages(topicMessages)
    }

    async checkConnection(timeoutMs?: number): Promise<void> {
        return (await this.producer()).checkConnection(timeoutMs)
    }

    async checkTopicExists(topic: string, timeoutMs?: number): Promise<void> {
        return (await this.producer()).checkTopicExists(topic, timeoutMs)
    }

    async disconnect(): Promise<void> {
        const connecting = this.connecting
        this.connecting = undefined
        const producer = await connecting?.catch(() => undefined)
        await producer?.disconnect()
    }
}
