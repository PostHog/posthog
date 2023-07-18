import { captureException, captureMessage } from '@sentry/node'
import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'
import { HighLevelProducer as RdKafkaProducer } from 'node-rdkafka-acosom'

import { KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS } from '../../../../config/kafka-topics'
import { createRdConnectionConfigFromEnvVars } from '../../../../kafka/config'
import { createKafkaProducer, disconnectProducer, produce } from '../../../../kafka/producer'
import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { createSessionReplayEvent } from '../../../../worker/ingestion/process-event'
import { eventDroppedCounter } from '../../metrics'
import { IncomingRecordingMessage } from './types'

export class ReplayEventsIngester {
    producer?: RdKafkaProducer

    constructor(private readonly serverConfig: PluginsServerConfig) {}

    public consume(event: IncomingRecordingMessage): Promise<any>[] | void {
        const warn = (text: string, labels: Record<string, any> = {}) =>
            status.warn('⚠️', text, {
                offset: event.metadata.offset,
                partition: event.metadata.partition,
                ...labels,
            })

        const drop = (reason: string, labels: Record<string, any> = {}) => {
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings',
                    drop_cause: reason,
                })
                .inc()

            warn(reason, {
                reason,
                ...labels,
            })
        }

        if (!this.producer) {
            return drop('producer_not_ready')
        }

        if (event.replayIngestionConsumer !== 'v2') {
            return drop('invalid_event_type')
        }

        try {
            const replayRecord = createSessionReplayEvent(
                randomUUID(),
                event.team_id,
                event.distinct_id,
                event.session_id,
                event.events
            )

            try {
                // the replay record timestamp has to be valid and be within a reasonable diff from now
                if (replayRecord !== null) {
                    const asDate = DateTime.fromSQL(replayRecord.first_timestamp)
                    if (!asDate.isValid || Math.abs(asDate.diffNow('months').months) >= 0.99) {
                        captureMessage(`Invalid replay record timestamp: ${replayRecord.first_timestamp} for event`, {
                            extra: {
                                replayRecord,
                                uuid: replayRecord.uuid,
                                timestamp: replayRecord.first_timestamp,
                            },
                            tags: {
                                team: event.team_id,
                                session_id: replayRecord.session_id,
                            },
                        })

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

            return [
                produce({
                    producer: this.producer,
                    topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
                    value: Buffer.from(JSON.stringify(replayRecord)),
                    key: event.session_id,
                }),
            ]
        } catch (error) {
            status.error('⚠️', 'processing_error', {
                error: error,
            })
        }
    }
    public async start(): Promise<void> {
        const connectionConfig = createRdConnectionConfigFromEnvVars(this.serverConfig)
        this.producer = await createKafkaProducer(connectionConfig)
        this.producer.connect()
    }

    public async stop(): Promise<void> {
        status.info('🔁', 'ReplayEventsIngester - stopping')

        if (this.producer && this.producer.isConnected()) {
            status.info('🔁', 'ReplayEventsIngester disconnecting kafka producer in batchConsumer stop')
            await disconnectProducer(this.producer)
        }
    }
}
