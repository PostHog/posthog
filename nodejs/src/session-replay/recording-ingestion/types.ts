// This is the incoming message from Kafka
import { Message } from 'node-rdkafka'

// Re-export shared RetentionPeriod so existing recording-ingestion imports still work
export { RetentionPeriod } from '../constants'

export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}

export type EachBatchHandler = (messages: Message[], context: { heartbeat: () => void }) => Promise<void>

export interface PartitionOffset {
    partition: number
    offset: number
}

export type CaptureIngestionWarningFn = (
    teamId: number,
    type: string,
    details: Record<string, any>,
    debounce?: { key?: string; alwaysSend?: boolean }
) => Promise<void>

export interface BatchMessageProcessor<TInput, TOutput> {
    parseBatch(messages: TInput[]): Promise<TOutput[]>
}
