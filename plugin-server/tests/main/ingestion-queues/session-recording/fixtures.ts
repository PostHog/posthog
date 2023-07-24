import { IncomingRecordingMessage } from '../../../../src/main/ingestion-queues/session-recording/types'
import jsonFullSnapshot from './data/snapshot-full.json'

export function createIncomingRecordingMessage(
    partialIncomingMessage: Partial<IncomingRecordingMessage> = {},
    partialMetadata: Partial<IncomingRecordingMessage['metadata']> = {}
): IncomingRecordingMessage {
    // the data on the kafka message is a compressed string.
    // it is a compressed $snapshot PostHog event
    // that has properties, and they have $snapshot_data
    // that will have data_items, which are the actual snapshots each individually compressed

    const message: IncomingRecordingMessage = {
        team_id: 1,
        distinct_id: 'distinct_id',
        session_id: 'session_id_1',
        window_id: 'window_id_1',
        events: [{ ...jsonFullSnapshot }],
        replayIngestionConsumer: 'v2',
        ...partialIncomingMessage,

        metadata: {
            topic: 'session_recording_events',
            partition: 1,
            offset: 1,
            timestamp: 1,
            ...partialIncomingMessage.metadata,
            ...partialMetadata,
        },
    }

    return message
}
