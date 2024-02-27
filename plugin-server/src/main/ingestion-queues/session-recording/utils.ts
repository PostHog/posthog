import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { KafkaConsumer, Message, MessageHeader, PartitionMetadata, TopicPartition } from 'node-rdkafka'
import path from 'path'

import { KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS } from '../../../config/kafka-topics'
import { PipelineEvent, RawEventMessage, RRWebEvent } from '../../../types'
import { status } from '../../../utils/status'
import { eventDroppedCounter } from '../metrics'
import { TeamIDWithConfig } from './session-recordings-consumer'
import { IncomingRecordingMessage, PersistedRecordingMessage } from './types'

export const convertToPersistedMessage = (message: IncomingRecordingMessage): PersistedRecordingMessage => {
    return {
        window_id: message.window_id,
        data: message.events,
    }
}

// Helper to return now as a milliseconds timestamp
export const now = () => DateTime.now().toMillis()

export const minDefined = (...args: (number | undefined)[]): number | undefined => {
    const definedArgs = args.filter((arg) => arg !== undefined) as number[]
    return definedArgs.length ? Math.min(...definedArgs) : undefined
}

export const maxDefined = (...args: (number | undefined)[]): number | undefined => {
    const definedArgs = args.filter((arg) => arg !== undefined) as number[]
    return definedArgs.length ? Math.max(...definedArgs) : undefined
}

export const bufferFileDir = (root: string) => path.join(root, 'session-buffer-files')

export const queryWatermarkOffsets = (
    kafkaConsumer: KafkaConsumer | undefined,
    partition: number,
    timeout = 10000
): Promise<[number, number]> => {
    return new Promise<[number, number]>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }

        kafkaConsumer.queryWatermarkOffsets(
            KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS,
            partition,
            timeout,
            (err, offsets) => {
                if (err) {
                    captureException(err)
                    status.error('🔥', 'Failed to query kafka watermark offsets', err)
                    return reject(err)
                }

                resolve([partition, offsets.highOffset])
            }
        )
    })
}

export const queryCommittedOffsets = (
    kafkaConsumer: KafkaConsumer | undefined,
    topicPartitions: TopicPartition[]
): Promise<Record<number, number>> => {
    return new Promise<Record<number, number>>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }

        kafkaConsumer.committed(topicPartitions, 10000, (err, offsets) => {
            if (err) {
                captureException(err)
                status.error('🔥', 'Failed to query kafka committed offsets', err)
                return reject(err)
            }

            resolve(
                offsets.reduce((acc, { partition, offset }) => {
                    acc[partition] = offset
                    return acc
                }, {} as Record<number, number>)
            )
        })
    })
}

export const getPartitionsForTopic = (
    kafkaConsumer: KafkaConsumer | undefined,
    topic = KAFKA_SESSION_RECORDING_SNAPSHOT_ITEM_EVENTS
): Promise<PartitionMetadata[]> => {
    return new Promise<PartitionMetadata[]>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }
        kafkaConsumer.getMetadata({ topic }, (err, meta) => {
            if (err) {
                captureException(err)
                status.error('🔥', 'Failed to get partition metadata', err)
                return reject(err)
            }

            return resolve(meta.topics.find((x) => x.name === topic)?.partitions ?? [])
        })
    })
}

export const getLagMultiplier = (lag: number, threshold = 1000000) => {
    if (lag < threshold) {
        return 1
    }

    return Math.max(0.1, 1 - (lag - threshold) / (threshold * 10))
}

export async function readTokenFromHeaders(
    headers: MessageHeader[] | undefined,
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
) {
    const tokenHeader = headers?.find((header: MessageHeader) => {
        // each header in the array is an object of key to value
        // because it's possible to have multiple headers with the same key
        // but, we don't support that. the first truthy match we find is the one we use
        return header.token
    })?.token

    const token = typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()

    let teamIdWithConfig: TeamIDWithConfig | null = null

    if (token) {
        teamIdWithConfig = await getTeamFn(token)
    }
    return { token, teamIdWithConfig }
}

export const parseKafkaMessage = async (
    message: Message,
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
): Promise<IncomingRecordingMessage | void> => {
    const dropMessage = (reason: string, extra?: Record<string, any>) => {
        eventDroppedCounter
            .labels({
                event_type: 'session_recordings_blob_ingestion',
                drop_cause: reason,
            })
            .inc()

        status.warn('⚠️', 'invalid_message', {
            reason,
            partition: message.partition,
            offset: message.offset,
            ...(extra || {}),
        })
    }

    if (!message.value || !message.timestamp) {
        // Typing says this can happen but in practice it shouldn't
        return dropMessage('message_value_or_timestamp_is_empty')
    }

    const headerResult = await readTokenFromHeaders(message.headers, getTeamFn)
    const token: string | undefined = headerResult.token
    let teamIdWithConfig: null | TeamIDWithConfig = headerResult.teamIdWithConfig

    // NB `==` so we're comparing undefined and null
    // if token was in the headers but, we could not load team config
    // then, we can return early
    if (!!token && (teamIdWithConfig == null || teamIdWithConfig.teamId == null)) {
        return dropMessage('header_token_present_team_missing_or_disabled', {
            token: token,
        })
    }

    let messagePayload: RawEventMessage
    let event: PipelineEvent

    try {
        messagePayload = JSON.parse(message.value.toString())
        event = JSON.parse(messagePayload.data)
    } catch (error) {
        return dropMessage('invalid_json', { error })
    }

    const { $snapshot_items, $session_id, $window_id, $snapshot_source } = event.properties || {}

    // NOTE: This is simple validation - ideally we should do proper schema based validation
    if (event.event !== '$snapshot_items' || !$snapshot_items || !$session_id) {
        return dropMessage('received_non_snapshot_message')
    }

    // TODO this mechanism is deprecated for blobby ingestion, we should remove it
    // once we're happy that the new mechanism is working
    // if there was not a token in the header then we try to load one from the message payload
    if (teamIdWithConfig == null && messagePayload.team_id == null && !messagePayload.token) {
        return dropMessage('no_token_in_header_or_payload')
    }

    if (teamIdWithConfig == null) {
        const token = messagePayload.token

        if (token) {
            teamIdWithConfig = await getTeamFn(token)
        }
    }

    // NB `==` so we're comparing undefined and null
    if (teamIdWithConfig == null || teamIdWithConfig.teamId == null) {
        return dropMessage('token_fallback_team_missing_or_disabled', {
            token: messagePayload.token,
            teamId: messagePayload.team_id,
            payloadTeamSource: messagePayload.team_id ? 'team' : messagePayload.token ? 'token' : 'unknown',
        })
    }
    // end of deprecated mechanism

    const events: RRWebEvent[] = $snapshot_items.filter((event: any) => {
        // we sometimes see events that are null
        // there will always be some unexpected data but, we should try to filter out the worst of it
        return event && event.timestamp
    })

    if (!events.length) {
        return dropMessage('message_contained_no_valid_rrweb_events', {
            token: messagePayload.token,
            teamId: messagePayload.team_id,
        })
    }

    return {
        metadata: {
            partition: message.partition,
            topic: message.topic,
            offset: message.offset,
            timestamp: message.timestamp,
            consoleLogIngestionEnabled: teamIdWithConfig.consoleLogIngestionEnabled,
        },

        team_id: teamIdWithConfig.teamId,
        distinct_id: messagePayload.distinct_id,
        session_id: $session_id,
        window_id: $window_id,
        events: events,
        snapshot_source: $snapshot_source,
    }
}

export const reduceRecordingMessages = (messages: IncomingRecordingMessage[]): IncomingRecordingMessage[] => {
    const reducedMessages: Record<string, IncomingRecordingMessage> = {}

    for (const message of messages) {
        const clonedMessage = { ...message }
        const key = `${clonedMessage.team_id}-${clonedMessage.session_id}-${clonedMessage.window_id}`
        if (!reducedMessages[key]) {
            reducedMessages[key] = clonedMessage
        } else {
            reducedMessages[key].events = [...reducedMessages[key].events, ...clonedMessage.events]
        }
    }

    return Object.values(reducedMessages)
}
