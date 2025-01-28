import { promisify } from 'node:util'
import { Message } from 'node-rdkafka'
import { gunzip } from 'zlib'

import { PipelineEvent, RawEventMessage, RRWebEvent } from '../../../../types'
import { status } from '../../../../utils/status'
import { KafkaMetrics } from './metrics'
import { ParsedMessageData } from './types'

const GZIP_HEADER = Uint8Array.from([0x1f, 0x8b, 0x08, 0x00])
const decompressWithGzip = promisify(gunzip)

export class KafkaMessageParser {
    public async parseBatch(messages: Message[]): Promise<ParsedMessageData[]> {
        const parsedMessages = await Promise.all(messages.map((message) => this.parseMessage(message)))
        return parsedMessages.filter((msg) => msg !== null) as ParsedMessageData[]
    }

    private async parseMessage(message: Message): Promise<ParsedMessageData | null> {
        const dropMessage = (reason: string, extra?: Record<string, any>) => {
            KafkaMetrics.incrementMessageDropped('session_recordings_blob_ingestion', reason)

            status.warn('⚠️', 'invalid_message', {
                reason,
                partition: message.partition,
                offset: message.offset,
                ...(extra || {}),
            })
            return null
        }

        if (!message.value || !message.timestamp) {
            return dropMessage('message_value_or_timestamp_is_empty')
        }

        let messagePayload: RawEventMessage
        let event: PipelineEvent

        let messageUnzipped = message.value
        try {
            if (this.isGzipped(message.value)) {
                // The type definition for gunzip is missing the Buffer type
                // https://nodejs.org/api/zlib.html#zlibgunzipbuffer-options-callback
                messageUnzipped = await decompressWithGzip(message.value as any)
            }
        } catch (error) {
            return dropMessage('invalid_gzip_data', { error })
        }

        try {
            messagePayload = JSON.parse(messageUnzipped.toString())
            event = JSON.parse(messagePayload.data)
        } catch (error) {
            return dropMessage('invalid_json', { error })
        }

        const { $snapshot_items, $session_id, $window_id, $snapshot_source } = event.properties || {}

        if (event.event !== '$snapshot_items' || !$snapshot_items || !$session_id) {
            return dropMessage('received_non_snapshot_message')
        }

        const events: RRWebEvent[] = $snapshot_items.filter((event: any) => event && event.timestamp)

        if (!events.length) {
            return dropMessage('message_contained_no_valid_rrweb_events')
        }

        return {
            metadata: {
                partition: message.partition,
                topic: message.topic,
                rawSize: message.size,
                offset: message.offset,
                timestamp: message.timestamp,
            },
            headers: message.headers,
            distinct_id: messagePayload.distinct_id,
            session_id: $session_id,
            eventsByWindowId: {
                [$window_id ?? '']: events,
            },
            eventsRange: {
                start: events[0].timestamp,
                end: events[events.length - 1].timestamp,
            },
            snapshot_source: $snapshot_source,
        }
    }

    private isGzipped(buffer: Buffer): boolean {
        return buffer.slice(0, GZIP_HEADER.length).equals(GZIP_HEADER)
    }
}
