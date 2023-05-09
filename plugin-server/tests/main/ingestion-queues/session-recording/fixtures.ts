import { randomUUID } from 'node:crypto'

import { IncomingRecordingMessage } from '../../../../src/main/ingestion-queues/session-recording/blob-ingester/types'
import { compressToString } from '../../../../src/main/ingestion-queues/session-recording/blob-ingester/utils'
import jsonFullSnapshot from './data/snapshot-full.json'

export function createIncomingRecordingMessage(data: Partial<IncomingRecordingMessage> = {}): IncomingRecordingMessage {
    return {
        metadata: {
            topic: 'session_recording_events',
            partition: 1,
            offset: 1,
            timestamp: undefined,
        },

        team_id: 1,
        distinct_id: 'distinct_id',
        session_id: 'session_id_1',
        window_id: 'window_id_1',

        // Properties data
        chunk_id: 'chunk_id_1',
        chunk_index: 0,
        chunk_count: 1,
        data: compressToString(JSON.stringify(jsonFullSnapshot)),
        compresssion: 'gzip-base64',
        has_full_snapshot: true,
        events_summary: [
            {
                timestamp: 1679568043305,
                type: 4,
                data: { href: 'http://localhost:3001/', width: 2560, height: 1304 },
            },
        ],
        ...data,
    }
}

export function createChunkedIncomingRecordingMessage(
    chunks: number,
    data: Partial<IncomingRecordingMessage> = {}
): IncomingRecordingMessage[] {
    const chunkId = randomUUID()
    const coreMessage = createIncomingRecordingMessage(data)
    const chunkLength = coreMessage.data.length / chunks
    const messages: IncomingRecordingMessage[] = []

    // Iterate over chunks count and clone the core message with the data split into chunks
    for (let i = 0; i < chunks; i++) {
        messages.push({
            ...coreMessage,
            chunk_id: chunkId,
            chunk_index: i,
            chunk_count: chunks,
            data: coreMessage.data.slice(i * chunkLength, (i + 1) * chunkLength),
        })
    }

    return messages
}
