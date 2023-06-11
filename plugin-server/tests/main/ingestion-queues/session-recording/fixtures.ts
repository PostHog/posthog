import { IncomingRecordingMessage } from '../../../../src/main/ingestion-queues/session-recording/blob-ingester/types'
import { compressToString } from '../../../../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import jsonFullSnapshot from './data/snapshot-full.json'

export function createIncomingRecordingMessage(
    partialIncomingMessage: Partial<IncomingRecordingMessage> = {},
    payload: Record<string, any> | null = null
): IncomingRecordingMessage {
    // the data on the kafka message is a compressed string.
    // it is a compressed $snapshot PostHog event
    // that has properties, and they have $snapshot_data
    // that will have data_items, which are the actual snapshots each individually compressed

    const { data: rrwebData, ...snapshotDataObject } = jsonFullSnapshot.properties.$snapshot_data

    return {
        team_id: 1,
        distinct_id: 'distinct_id',
        session_id: 'session_id_1',
        window_id: 'window_id_1',

        // Properties data
        data_items: [compressToString(JSON.stringify(payload || rrwebData))],
        compression: 'gzip-base64',
        has_full_snapshot: true,
        events_summary: [
            {
                timestamp: 1679568043305,
                type: 4,
                data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
            },
        ],
        ...snapshotDataObject,
        ...partialIncomingMessage,
        metadata: {
            topic: 'session_recording_events',
            partition: 1,
            offset: 1,
            timestamp: 1,
            ...partialIncomingMessage.metadata,
        },
    }
}
