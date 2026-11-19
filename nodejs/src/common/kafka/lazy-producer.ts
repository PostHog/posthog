import { KafkaProducer, ProducerMessage, TopicMessage } from './producer'

const FIRST_RETRY_MS = 5_000
// node-rdkafka leaks a little native memory on each failed connect, so a long outage retries rarely.
const MAX_RETRY_MS = 5 * 60_000
const CHECK_TIMEOUT_MS = 10_000

// Connects in the background, retrying with backoff, and fails produces until connected, so a cluster that is
// down fails the produces that pick it rather than the boot of every pod that registers it. A produce never waits on
// a connect: a message held past its caller's deadline could land after the caller already answered that it failed.
export class LazyKafkaProducer implements KafkaProducer {
    private connected?: KafkaProducer
    private connecting?: Promise<KafkaProducer>
    private retry?: NodeJS.Timeout
    private retryMs = FIRST_RETRY_MS
    private closed = false

    constructor(private connect: () => Promise<KafkaProducer>) {
        void this.startConnect()
    }

    /** Resolves once connected, after a failed attempt, or after `timeoutMs`, whichever comes first. Never rejects. */
    async waitConnected(timeoutMs: number): Promise<void> {
        let timer: NodeJS.Timeout | undefined
        const timeout = new Promise<void>((resolve) => {
            timer = setTimeout(resolve, timeoutMs)
        })
        await Promise.race([
            this.connecting?.then(
                () => undefined,
                () => undefined
            ),
            timeout,
        ])
        clearTimeout(timer)
    }

    private startConnect(): Promise<KafkaProducer> | undefined {
        if (this.closed || this.connected || this.connecting || this.retry) {
            return this.connecting
        }
        const connecting = this.connect().then(
            (producer) => {
                if (this.closed) {
                    void producer.disconnect().catch(() => undefined)
                } else {
                    this.connected = producer
                    this.retryMs = FIRST_RETRY_MS
                }
                return producer
            },
            (error) => {
                this.connecting = undefined
                if (!this.closed) {
                    this.retry = setTimeout(() => {
                        this.retry = undefined
                        void this.startConnect()
                    }, this.retryMs)
                    this.retryMs = Math.min(this.retryMs * 2, MAX_RETRY_MS)
                    this.retry.unref()
                }
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

    async checkConnection(timeoutMs = CHECK_TIMEOUT_MS): Promise<void> {
        const remainingMs = await this.connectedWithin(timeoutMs)
        return this.ready().checkConnection(remainingMs)
    }

    async checkTopicExists(topic: string, timeoutMs = CHECK_TIMEOUT_MS): Promise<void> {
        const remainingMs = await this.connectedWithin(timeoutMs)
        return this.ready().checkTopicExists(topic, remainingMs)
    }

    // The connect and the check share one timeout, so a check never takes longer than it was given.
    private async connectedWithin(timeoutMs: number): Promise<number> {
        const startedAt = Date.now()
        await this.waitConnected(timeoutMs)
        return Math.max(timeoutMs - (Date.now() - startedAt), 1)
    }

    async disconnect(): Promise<void> {
        this.closed = true
        clearTimeout(this.retry)
        this.retry = undefined
        const connected = this.connected
        this.connected = undefined
        this.connecting = undefined
        await connected?.disconnect()
    }
}
