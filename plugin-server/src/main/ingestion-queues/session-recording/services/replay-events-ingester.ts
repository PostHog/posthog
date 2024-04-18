import { captureException } from '@sentry/node'
import { randomUUID } from 'crypto'
import { DateTime } from 'luxon'
import { HighLevelProducer as RdKafkaProducer } from 'node-rdkafka'
import { Counter } from 'prom-client'

import { KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS } from '../../../../config/kafka-topics'
import { produce } from '../../../../kafka/producer'
import { KafkaProducerWrapper } from '../../../../utils/db/kafka-producer-wrapper'
import { status } from '../../../../utils/status'
import { captureIngestionWarning } from '../../../../worker/ingestion/utils'
import { createSessionReplayEvent } from '../process-event'
import { IncomingRecordingMessage } from '../types'
import { BaseIngester } from './base-ingester'
import { OffsetHighWaterMarker } from './offset-high-water-marker'

const HIGH_WATERMARK_KEY = 'session_replay_events_ingester'

const replayEventsCounter = new Counter({
    name: 'replay_events_ingested',
    help: 'Number of Replay events successfully ingested',
})

export class ReplayEventsIngester extends BaseIngester {
    constructor(producer: RdKafkaProducer, persistentHighWaterMarker?: OffsetHighWaterMarker) {
        super(HIGH_WATERMARK_KEY, producer, persistentHighWaterMarker)
    }

    public async consume(event: IncomingRecordingMessage): Promise<Promise<number | null | undefined>[] | void> {
        if (!this.producer) {
            return this.drop('producer_not_ready')
        }
        if (
            await this.persistentHighWaterMarker?.isBelowHighWaterMark(
                event.metadata,
                HIGH_WATERMARK_KEY,
                event.metadata.highOffset
            )
        ) {
            return this.drop('high_water_mark')
        }
        try {
            const rrwebEvents = Object.values(event.eventsByWindowId).reduce((acc, val) => acc.concat(val), [])
            const replayRecord = createSessionReplayEvent(
                randomUUID(),
                event.team_id,
                event.distinct_id,
                event.session_id,
                rrwebEvents,
                event.snapshot_source
            )
            try {
                // the replay record timestamp has to be valid and be within a reasonable diff from now
                if (replayRecord !== null) {
                    const asDate = DateTime.fromSQL(replayRecord.first_timestamp)
                    if (!asDate.isValid || Math.abs(asDate.diffNow('day').days) >= 7) {
                        await captureIngestionWarning(
                            new KafkaProducerWrapper(this.producer),
                            event.team_id,
                            !asDate.isValid ? 'replay_timestamp_invalid' : 'replay_timestamp_too_far',
                            {
                                replayRecord,
                                timestamp: replayRecord.first_timestamp,
                                isValid: asDate.isValid,
                                daysFromNow: Math.round(Math.abs(asDate.diffNow('day').days)),
                                processingTimestamp: DateTime.now().toISO(),
                            },
                            { key: event.session_id }
                        )
                        return this.drop('invalid_timestamp')
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
                return this.drop('session_replay_summarizer_error')
            }
            replayEventsCounter.inc()
            return [
                produce({
                    producer: this.producer,
                    topic: KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS,
                    value: Buffer.from(JSON.stringify(replayRecord)),
                    key: event.session_id,
                    waitForAck: true,
                }),
            ]
        } catch (error) {
            status.error('⚠️', `[${this.label}] processing_error`, {
                error: error,
            })
        }
    }
}
