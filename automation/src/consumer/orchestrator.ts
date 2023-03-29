import { EachMessagePayload } from 'kafkajs'
import { counterMessagesReceived } from '../utils/metrics'
import { createLogger } from '../utils/logger'
import { config } from '../config'
import { consumer, producer } from '../utils/kafka'
import { EventType } from '../types'

const logger = createLogger('ingester')

const TOPICS_TO_CONSUME = [config.topics.captureEvents]

export class Orchestrator {
    public async consume(event: EventType): Promise<void> {
        logger.info('Consuming event!')
        console.log(event)
    }

    public async handleKafkaMessage({ topic, partition, message }: EachMessagePayload): Promise<void> {
        counterMessagesReceived.add(1)
        const data = JSON.parse(message.value.toString())

        data.properties = JSON.parse(data.properties)
        data.person_properties = JSON.parse(data.person_properties)
        data.group_properties = JSON.parse(data.group_properties)

        this.consume(data as unknown as EventType)
    }

    public start(): void {
        consumer.connect()
        consumer.subscribe({ topics: TOPICS_TO_CONSUME })
        producer.connect()

        consumer.run({
            autoCommit: true,
            eachMessage: async (message) => {
                this.handleKafkaMessage(message)
            },
        })
    }

    public async stop(): Promise<void> {
        await consumer.disconnect()
        await producer.disconnect()
    }
}
