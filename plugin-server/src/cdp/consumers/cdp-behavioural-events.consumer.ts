import { createHash } from 'crypto'
import { Message } from 'node-rdkafka'
import { Histogram } from 'prom-client'

import { KAFKA_CDP_PERSON_PERFORMED_EVENT, KAFKA_EVENTS_JSON } from '../../config/kafka-topics'
import { KafkaConsumer } from '../../kafka/consumer'
import { runInstrumentedFunction } from '../../main/utils'
import { Hub, RawClickHouseEvent } from '../../types'
import { parseJSON } from '../../utils/json-parse'
import { logger } from '../../utils/logger'
import { CdpConsumerBase } from './cdp-base.consumer'

export type PersonEventPayload = {
    type: 'person-performed-event'
    personId: string
    eventName: string
    teamId: number
}

export type CohortFilterPayload = {
    type: 'behavioural-filter-match-event'
    personId: string
    teamId: number
    filterHash: string
    date: string
}

export type ProducedEvent = {
    key: string
    payload: PersonEventPayload | CohortFilterPayload
}

export const histogramBatchProcessingSteps = new Histogram({
    name: 'cdp_behavioural_batch_processing_steps_duration_ms',
    help: 'Time spent in different batch processing steps',
    labelNames: ['step'],
    buckets: [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500],
})

export class CdpBehaviouralEventsConsumer extends CdpConsumerBase {
    protected name = 'CdpBehaviouralEventsConsumer'
    protected kafkaConsumer: KafkaConsumer

    constructor(hub: Hub, topic: string = KAFKA_EVENTS_JSON, groupId: string = 'cdp-behavioural-events-consumer') {
        super(hub)
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic })
    }

    protected async publishEvents(events: ProducedEvent[]): Promise<void> {
        if (!this.kafkaProducer || events.length === 0) {
            return
        }

        try {
            const messages = events.map((event) => ({
                topic: KAFKA_CDP_PERSON_PERFORMED_EVENT,
                value: JSON.stringify(event),
                key: event.key,
            }))

            await this.kafkaProducer.queueMessages({ topic: KAFKA_CDP_PERSON_PERFORMED_EVENT, messages })
        } catch (error) {
            logger.error('Error publishing events', {
                error,
                queueLength: events.length,
            })
            // Don't clear queue on error - messages will be retried with next batch
        }
    }

    // This consumer always parses from kafka and creates events directly
    public async _parseKafkaBatch(messages: Message[]): Promise<ProducedEvent[]> {
        return await this.runWithHeartbeat(() =>
            runInstrumentedFunction({
                statsKey: `cdpBehaviouralEventsConsumer.handleEachBatch.parseKafkaMessages`,
                func: () => {
                    const events: ProducedEvent[] = []
                    messages.forEach((message) => {
                        try {
                            const clickHouseEvent = parseJSON(message.value!.toString()) as RawClickHouseEvent

                            if (!clickHouseEvent.person_id) {
                                const error = new Error(
                                    `Event missing person_id. Event: ${clickHouseEvent.event}, Team: ${clickHouseEvent.team_id}, Event-UUID: ${clickHouseEvent.uuid}`
                                )
                                logger.error('Event missing person_id', {
                                    teamId: clickHouseEvent.team_id,
                                    event: clickHouseEvent.event,
                                    uuid: clickHouseEvent.uuid,
                                })
                                throw error
                            }

                            const timestamp = Math.floor(new Date(clickHouseEvent.timestamp).getTime() / 1000)
                            const date = new Date(timestamp * 1000).toISOString().split('T')[0]

                            // Create person-performed-event with partition key: teamId:personId:eventName
                            const personPerformedEventKey = `${clickHouseEvent.team_id}:${clickHouseEvent.person_id}:${clickHouseEvent.event}`
                            const personPerformedEvent: ProducedEvent = {
                                key: personPerformedEventKey,
                                payload: {
                                    type: 'person-performed-event',
                                    personId: clickHouseEvent.person_id,
                                    eventName: clickHouseEvent.event,
                                    teamId: clickHouseEvent.team_id,
                                },
                            }

                            // Create behavioural-filter-match-event with partition key: teamId:personId:hash:date
                            const filterHash = createHash('sha256').update(clickHouseEvent.event).digest('hex')
                            const behaviouralFilterMatchEventKey = `${clickHouseEvent.team_id}:${clickHouseEvent.person_id}:${filterHash}:${date}`
                            const behaviouralFilterMatchEvent: ProducedEvent = {
                                key: behaviouralFilterMatchEventKey,
                                payload: {
                                    type: 'behavioural-filter-match-event',
                                    teamId: clickHouseEvent.team_id,
                                    personId: clickHouseEvent.person_id,
                                    filterHash: filterHash,
                                    date: date,
                                },
                            }

                            events.push(personPerformedEvent, behaviouralFilterMatchEvent)
                        } catch (e) {
                            logger.error('Error parsing message', e)
                        }
                    })
                    // Return Promise.resolve to satisfy runInstrumentedFunction's Promise return type
                    return Promise.resolve(events)
                },
            })
        )
    }

    public async start(): Promise<void> {
        await super.start()

        // Start consuming messages
        await this.kafkaConsumer.connect(async (messages) => {
            logger.info('🔁', `${this.name} - handling batch`, {
                size: messages.length,
            })

            return await this.runInstrumented('handleEachBatch', async () => {
                const events = await this._parseKafkaBatch(messages)
                // Publish events in background
                const backgroundTask = this.publishEvents(events).catch((error) => {
                    throw new Error(`Failed to publish behavioural events: ${error.message}`)
                })

                return { backgroundTask }
            })
        })
    }

    public async stop(): Promise<void> {
        logger.info('💤', 'Stopping behavioural events consumer...')
        await this.kafkaConsumer.disconnect()

        // IMPORTANT: super always comes last
        await super.stop()
        logger.info('💤', 'Behavioural events consumer stopped!')
    }

    public isHealthy() {
        return this.kafkaConsumer.isHealthy()
    }
}
