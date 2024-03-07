import { Message } from 'node-rdkafka'

import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../../src/config/kafka-topics'
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
        eventsByWindowId: {
            window_id_1: [{ ...jsonFullSnapshot }],
        },
        eventsRange: {
            start: jsonFullSnapshot.timestamp,
            end: jsonFullSnapshot.timestamp,
        },
        snapshot_source: null,
        ...partialIncomingMessage,

        metadata: {
            topic: 'session_recording_events',
            partition: 1,
            lowOffset: 1,
            highOffset: 1,
            timestamp: 1,
            ...partialIncomingMessage.metadata,
            ...partialMetadata,
        },
    }

    return message
}

export function createKafkaMessage(
    token: number | string,
    messageOverrides: Partial<Message> = {},
    eventProperties: Record<string, any> = {}
): Message {
    const message: Message = {
        partition: 1,
        topic: KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
        offset: 0,
        timestamp: messageOverrides.timestamp ?? Date.now(),
        size: 1,
        ...messageOverrides,

        value: Buffer.from(
            JSON.stringify({
                distinct_id: 'distinct_id',
                token: token,
                data: JSON.stringify({
                    event: '$snapshot_items',
                    properties: {
                        $session_id: 'session_id_1',
                        $window_id: 'window_id_1',
                        $snapshot_items: [{ ...jsonFullSnapshot }],
                        ...eventProperties,
                    },
                }),
            })
        ),
    }

    return message
}

export function createTP(partition: number, topic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS) {
    return { topic, partition }
}
