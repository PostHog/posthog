import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS } from '../../../../config/kafka-topics'
import { findOffsetsToCommit } from '../../../../kafka/consumer'
import { retryOnDependencyUnavailableError } from '../../../../kafka/error-handling'
import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { logger } from '../../../../utils/logger'
import { captureException } from '../../../../utils/posthog'
import { captureIngestionWarning } from '../../../../worker/ingestion/utils'
import { eventDroppedCounter } from '../../metrics'
import { createSessionReplayEvent, RRWebEventType } from '../process-event'
import { IncomingRecordingMessage } from '../types'
import { OffsetHighWaterMarker } from './offset-high-water-marker'

const HIGH_WATERMARK_KEY = 'session_replay_events_ingester'

const replayEventsCounter = new Counter({
    name: 'replay_events_ingested',
    help: 'Number of Replay events successfully ingested',
    labelNames: ['snapshot_source'],
})

const dataIngestedCounter = new Counter({
    name: 'replay_data_ingested',
    help: 'Amount of data being ingested',
    labelNames: ['snapshot_source'],
})

export class ReplayEventsIngester {
    constructor(
        private readonly producer: KafkaProducerWrapper,
        private readonly persistentHighWaterMarker?: OffsetHighWaterMarker,
        private readonly metadataSwitchoverDate: Date | null = null
    ) {}

    public async consumeBatch(messages: IncomingRecordingMessage[]) {
        const pendingProduceRequests: Promise<void>[] = []

        for (const message of messages) {
            const results = await retryOnDependencyUnavailableError(() => this.consume(message))
            if (results) {
                results.forEach((result) => {
                    pendingProduceRequests.push(result)
                })
            }
        }

        // On each loop, we flush the producer to ensure that all messages
        // are sent to Kafka.
        try {
            await this.producer.flush()
        } catch (error) {
            // Rather than handling errors from flush, we instead handle
            // errors per produce request, which gives us a little more
            // flexibility in terms of deciding if it is a terminal
            // error or not.
        }

        // We wait on all the produce requests to complete. After the
        // flush they should all have been resolved/rejected already. If
        // we get an intermittent error, such as a Kafka broker being
        // unavailable, we will throw. We are relying on the Producer
        // already having handled retries internally.
        for (const produceRequest of pendingProduceRequests) {
            try {
                await produceRequest
            } catch (error) {
                logger.error('🔁', '[replay-events] main_loop_error', { error })

                if (error?.isRetriable) {
                    // We assume that if the error is retriable, then we
                    // are probably in a state where e.g. Kafka is down
                    // temporarily, and we would rather simply throw and
                    // have the process restarted.
                    throw error
                }
            }
        }

        if (this.persistentHighWaterMarker) {
            const topicPartitionOffsets = findOffsetsToCommit(
                messages.map((message) => ({
                    topic: message.metadata.topic,
                    partition: message.metadata.partition,
                    offset: message.metadata.highOffset,
                }))
            )

            await Promise.all(
                topicPartitionOffsets.map((tpo) =>
                    this.persistentHighWaterMarker!.add(tpo, HIGH_WATERMARK_KEY, tpo.offset)
                )
            )
        }
    }

    public async consume(event: IncomingRecordingMessage): Promise<Promise<void>[] | void> {
        const drop = (reason: string) => {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_replay_events',
                    drop_cause: reason,
                })
                .inc()
        }

        if (!this.producer) {
            return drop('producer_not_ready')
        }

        if (
            await this.persistentHighWaterMarker?.isBelowHighWaterMark(
                event.metadata,
                HIGH_WATERMARK_KEY,
                event.metadata.highOffset
            )
        ) {
            return drop('high_water_mark')
        }

        try {
            const switchoverMs = this.metadataSwitchoverDate?.getTime()
            if (switchoverMs && event.metadata.timestamp >= switchoverMs) {
                return drop('after_switchover_date')
            }

            const rrwebEvents = Object.values(event.eventsByWindowId).reduce((acc, val) => acc.concat(val), [])

            const { event: replayRecord } = createSessionReplayEvent(
                randomUUID(),
                event.team_id,
                event.distinct_id,
                event.session_id,
                rrwebEvents,
                event.snapshot_source,
                event.snapshot_library
            )

            try {
                // the replay record timestamp has to be valid and be within a reasonable diff from now
                if (replayRecord !== null) {
                    const asDate = DateTime.fromSQL(replayRecord.first_timestamp)
                    if (!asDate.isValid || Math.abs(asDate.diffNow('day').days) >= 7) {
                        const eventTypes: { type: number; timestamp: number }[] = []
                        const customEvents: typeof rrwebEvents = []

                        for (const event of rrwebEvents) {
                            eventTypes.push({ type: event.type, timestamp: event.timestamp })
                            if (event.type === RRWebEventType.Custom) {
                                customEvents.push(event)
                            }
                        }

                        await captureIngestionWarning(
                            this.producer,
                            event.team_id,
                            !asDate.isValid ? 'replay_timestamp_invalid' : 'replay_timestamp_too_far',
                            {
                                replayRecord,
                                timestamp: replayRecord.first_timestamp,
                                isValid: asDate.isValid,
                                daysFromNow: Math.round(Math.abs(asDate.diffNow('day').days)),
                                processingTimestamp: DateTime.now().toISO(),
                                eventTypes,
                                customEvents,
                            },
                            { key: event.session_id }
                        )
                        return drop('invalid_timestamp')
                    }
                }
            } catch (e) {
                captureException(e, {
                    extra: {
                        replayRecord,
                    },
                    tags: {
                        team: event.team_id,
                        session_id: event.session_id,
                    },
                })

                return drop('session_replay_summarizer_error')
            }

            replayEventsCounter.inc({ snapshot_source: replayRecord.snapshot_source ?? undefined })
            dataIngestedCounter.inc({ snapshot_source: replayRecord.snapshot_source ?? undefined }, replayRecord.size)

            return [
                this.producer.queueMessages({
                    topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
                    messages: [
                        {
                            value: JSON.stringify(replayRecord),
                            key: event.session_id,
                        },
                    ],
                }),
            ]
        } catch (error) {
            logger.error('⚠️', '[replay-events] processing_error', {
                error: error,
            })
        }
    }
}
