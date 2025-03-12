import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { ClickHouseTimestamp, LogLevel } from '../../../../types'
import { status } from '../../../../utils/status'

export type ConsoleLogEntry = {
    team_id: number
    message: string
    level: LogLevel
    log_source: 'session_replay'
    log_source_id: string
    instance_id: string | null
    timestamp: ClickHouseTimestamp
    batch_id: string
}

export class SessionConsoleLogStore {
    constructor(private readonly producer: KafkaProducerWrapper, private readonly topic: string) {
        status.debug('🔍', 'session_console_log_store_created')
        if (!this.topic) {
            status.warn('⚠️', 'session_console_log_store_no_topic_configured')
        }
    }

    public async storeSessionConsoleLogs(logs: ConsoleLogEntry[]): Promise<void> {
        if (logs.length === 0 || !this.topic) {
            return
        }

        await this.producer.queueMessages({
            topic: this.topic,
            messages: logs.map((log) => ({
                value: JSON.stringify(log),
                key: log.log_source_id, // Using session_id as the key for partitioning
            })),
        })
    }
}
