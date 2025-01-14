// This is the incoming message from Kafka

import { Message } from 'node-rdkafka'

import { MessageWithTeam } from './teams/types'

export type PersistedRecordingMessage = {
    window_id?: string
    data: any
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
