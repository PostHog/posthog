// This is the incoming message from Kafka

import { Message } from 'node-rdkafka'

import { MessageWithTeam } from './teams/types'

export type PersistedRecordingMessage = {
    window_id?: string
    data: any
}

export type BatchStats = {
    /**
     * Subset of the kafka Message class, used to report metrics only
     */
    readonly partition: number
    readonly offset: number
    readonly timestamp?: number
}

export type EachBatchHandler = (messages: Message[], context: { heartbeat: () => void }) => Promise<void>

export type CaptureIngestionWarningFn = (
    teamId: number,
    type: string,
    details: Record<string, any>,
    debounce?: { key?: string; alwaysSend?: boolean }
) => Promise<void>

export interface BatchMessageParser {
    parseBatch(messages: Message[] | MessageWithTeam[]): Promise<MessageWithTeam[]>
}
