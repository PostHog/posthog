import { KAFKA_INGESTION_WARNINGS } from '../config/kafka-topics'
import { KafkaProducerWrapper } from '../kafka/producer'
import { TeamId, TimestampFormat } from '../types'
import { status } from './status'
import { IngestionWarningLimiter } from './token-bucket'
import { castTimestampOrNow } from './utils'

// These get displayed under Data Management > Ingestion Warnings
// These warnings get displayed to end users. Make sure these errors are actionable and useful for them and
// also update IngestionWarningsView.tsx to display useful context.
export async function captureIngestionWarning(
    kafkaProducer: KafkaProducerWrapper,
    teamId: TeamId,
    type: string,
    details: Record<string, any>,
    /**
     * captureIngestionWarning will debounce calls using team id and type as the key
     * you can provide additional config in debounce.key to add to that key
     * for example to debounce by specific user id you can use debounce: { key: user_id }
     *
     * if alwaysSend is true, the message will be sent regardless of the debounce key
     * you can use this when a message is rare enough or important enough that it should always be sent
     */
    debounce?: { key?: string; alwaysSend?: boolean }
) {
    const limiter_key = `${teamId}:${type}:${debounce?.key || ''}`
    if (!!debounce?.alwaysSend || IngestionWarningLimiter.consume(limiter_key, 1)) {
        // TODO: Either here or in follow up change this to an await as we do care.
        void kafkaProducer
            .queueMessages({
                topic: KAFKA_INGESTION_WARNINGS,
                messages: [
                    {
                        value: JSON.stringify({
                            team_id: teamId,
                            type: type,
                            source: 'plugin-server',
                            details: JSON.stringify(details),
                            timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                        }),
                    },
                ],
            })
            .catch((error) => {
                status.warn('⚠️', 'Failed to produce ingestion warning', {
                    error,
                    team_id: teamId,
                    type,
                    details,
                })
            })
    }
    return Promise.resolve()
}
