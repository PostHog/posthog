import { KafkaProducerWrapper } from '../../../../kafka/producer'
import { ClickHouseTimestamp } from '../../../../types'
import { logger } from '../../../../utils/logger'
import { ConsoleLogLevel } from '../rrweb-types'
import { SessionBatchMetrics } from './metrics'

export type ConsoleLogEntry = {
    team_id: number
    message: string
    level: ConsoleLogLevel
    log_source: 'session_replay'
    log_source_id: string
    instance_id: string | null
    timestamp: ClickHouseTimestamp
    batch_id: string
}

export class SessionConsoleLogStore {
    private consoleLogsCount = 0

    constructor(private readonly producer: KafkaProducerWrapper, private readonly topic: string) {
        logger.debug('session_console_log_store_created')
        if (!this.topic) {
            logger.warn('session_console_log_store_no_topic_configured')
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

        this.consoleLogsCount += logs.length
        logger.debug(`stored ${logs.length} console logs for session ${logs[0].log_source_id}`)
        SessionBatchMetrics.incrementConsoleLogsStored(logs.length)
    }

    public async flush(): Promise<void> {
        logger.info(`flushing ${this.consoleLogsCount} console logs`)
        await this.producer.flush()
        this.consoleLogsCount = 0
    }
}
