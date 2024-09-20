import { captureException } from '@sentry/node'
import { DateTime } from 'luxon'
import { KafkaConsumer, Message, MessageHeader, PartitionMetadata } from 'node-rdkafka'
import path from 'path'
import { Counter } from 'prom-client'

import { PipelineEvent, RawEventMessage, RRWebEvent } from '../../../types'
import { KafkaProducerWrapper } from '../../../utils/db/kafka-producer-wrapper'
import { status } from '../../../utils/status'
import { captureIngestionWarning } from '../../../worker/ingestion/utils'
import { eventDroppedCounter } from '../metrics'
import { TeamIDWithConfig } from './session-recordings-consumer'
import { IncomingRecordingMessage, ParsedBatch, PersistedRecordingMessage } from './types'

const { promisify } = require('node:util')
const { unzip } = require('node:zlib')

const GZIP_HEADER = Buffer.from([0x1f, 0x8b, 0x08, 0x00])

function isGzipped(buffer: Buffer): boolean {
    if (buffer.length < GZIP_HEADER.length) {
        return false
    }

    for (let i = 0; i < GZIP_HEADER.length; i++) {
        if (buffer[i] !== GZIP_HEADER[i]) {
            return false
        }
    }

    return true
}

const do_unzip = promisify(unzip)

const counterKafkaMessageReceived = new Counter({
    name: 'recording_blob_ingestion_kafka_message_received',
    help: 'The number of messages we have received from Kafka',
    labelNames: ['partition'],
})

const counterLibVersionWarning = new Counter({
    name: 'lib_version_warning_counter',
    help: 'the number of times we have seen a message with a lib version that is too old, each _might_ cause an ingestion warning if not debounced',
})

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
    topic: string,
    partition: number,
    timeout = 10000
): Promise<[number, number]> => {
    return new Promise<[number, number]>((resolve, reject) => {
        if (!kafkaConsumer) {
            return reject('Not connected')
        }

        kafkaConsumer.queryWatermarkOffsets(topic, partition, timeout, (err, offsets) => {
            if (err) {
                captureException(err)
                status.error('🔥', 'Failed to query kafka watermark offsets', err)
                return reject(err)
            }

            resolve([partition, offsets.highOffset])
        })
    })
}

export const getPartitionsForTopic = (
    kafkaConsumer: KafkaConsumer | undefined,
    topic: string
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

function readLibVersionFromHeaders(headers: MessageHeader[] | undefined): string | undefined {
    const libVersionHeader = headers?.find((header) => {
        return header['lib_version']
    })?.['lib_version']
    return typeof libVersionHeader === 'string' ? libVersionHeader : libVersionHeader?.toString()
}

interface LibVersion {
    major: number
    minor: number
}

function parseVersion(libVersion: string | undefined): LibVersion | undefined {
    try {
        let majorString: string | undefined = undefined
        let minorString: string | undefined = undefined
        if (libVersion && libVersion.includes('.')) {
            const splat = libVersion.split('.')
            // very loose check for three part semantic version number
            if (splat.length === 3) {
                majorString = splat[0]
                minorString = splat[1]
            }
        }
        const validMajor = majorString && !isNaN(parseInt(majorString))
        const validMinor = minorString && !isNaN(parseInt(minorString))
        return validMajor && validMinor
            ? {
                  major: parseInt(majorString as string),
                  minor: parseInt(minorString as string),
              }
            : undefined
    } catch (e) {
        status.warn('⚠️', 'could_not_read_minor_lib_version', { libVersion })
        return undefined
    }
}

export const parseKafkaMessage = async (
    message: Message,
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>,
    ingestionWarningProducer: KafkaProducerWrapper | undefined
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
    const teamIdWithConfig: null | TeamIDWithConfig = headerResult.teamIdWithConfig

    if (!token) {
        return dropMessage('no_token_in_header')
    }

    // NB `==` so we're comparing undefined and null
    // if token was in the headers but, we could not load team config
    // then, we can return early
    if (teamIdWithConfig == null || teamIdWithConfig.teamId == null) {
        return dropMessage('header_token_present_team_missing_or_disabled', {
            token: token,
        })
    }

    // this has to be ahead of the payload parsing in case we start dropping traffic from older versions
    if (!!ingestionWarningProducer && !!teamIdWithConfig.teamId) {
        const libVersion = readLibVersionFromHeaders(message.headers)
        const parsedVersion = parseVersion(libVersion)
        /**
         * We introduced SVG mutation throttling in version 1.74.0 fix: Recording throttling for SVG-like things (#758)
         * and improvements like jitter on retry and better batching in session recording in earlier versions
         * So, versions older than 1.75.0 can cause ingestion pressure or incidents
         * because they send much more information and more messages for the same recording
         */
        if (parsedVersion && parsedVersion.major === 1 && parsedVersion.minor < 75) {
            counterLibVersionWarning.inc()

            await captureIngestionWarning(
                ingestionWarningProducer,
                teamIdWithConfig.teamId,
                'replay_lib_version_too_old',
                {
                    libVersion,
                    parsedVersion,
                },
                { key: libVersion || 'unknown' }
            )
        }
    }

    let messagePayload: RawEventMessage
    let event: PipelineEvent

    let messageUnzipped = message.value
    try {
        if (isGzipped(message.value)) {
            messageUnzipped = await do_unzip(message.value)
        }
    } catch (error) {
        return dropMessage('invalid_gzip_data', { error, team_id: teamIdWithConfig.teamId })
    }

    try {
        messagePayload = JSON.parse(messageUnzipped.toString())
        event = JSON.parse(messagePayload.data)
    } catch (error) {
        return dropMessage('invalid_json', { error, team_id: teamIdWithConfig.teamId })
    }

    const { $snapshot_items, $session_id, $window_id, $snapshot_source } = event.properties || {}

    // NOTE: This is simple validation - ideally we should do proper schema based validation
    if (event.event !== '$snapshot_items' || !$snapshot_items || !$session_id) {
        return dropMessage('received_non_snapshot_message', { team_id: teamIdWithConfig.teamId })
    }

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
            rawSize: message.size,
            lowOffset: message.offset,
            highOffset: message.offset,
            timestamp: message.timestamp,
            consoleLogIngestionEnabled: teamIdWithConfig.consoleLogIngestionEnabled,
        },

        team_id: teamIdWithConfig.teamId,
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

export const parseKafkaBatch = async (
    /**
     * Parses and validates a batch of Kafka messages, merges messages for the same session into a single
     * IncomingRecordingMessage to amortize processing and computes per-partition statistics.
     */
    messages: Message[],
    getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>,
    ingestionWarningProducer: KafkaProducerWrapper | undefined
): Promise<ParsedBatch> => {
    const lastMessageForPartition: Map<number, Message> = new Map()
    const parsedSessions: Map<string, IncomingRecordingMessage> = new Map()

    for (const message of messages) {
        const partition = message.partition
        lastMessageForPartition.set(partition, message) // We can assume messages for a single partition are ordered
        counterKafkaMessageReceived.inc({ partition })

        const parsedMessage = await parseKafkaMessage(message, getTeamFn, ingestionWarningProducer)
        if (!parsedMessage) {
            continue
        }

        const sessionKey = `${parsedMessage.team_id}:${parsedMessage.session_id}`
        const existingMessage = parsedSessions.get(sessionKey)

        if (existingMessage === undefined) {
            // First message for this session key, store it and continue looping for more
            parsedSessions.set(sessionKey, parsedMessage)
            continue
        }

        for (const [windowId, events] of Object.entries(parsedMessage.eventsByWindowId)) {
            existingMessage.eventsByWindowId[windowId] = (existingMessage.eventsByWindowId[windowId] || []).concat(
                events
            )
        }

        existingMessage.metadata.rawSize += parsedMessage.metadata.rawSize

        // Update the events ranges
        existingMessage.metadata.lowOffset = Math.min(
            existingMessage.metadata.lowOffset,
            parsedMessage.metadata.lowOffset
        )
        existingMessage.metadata.highOffset = Math.max(
            existingMessage.metadata.highOffset,
            parsedMessage.metadata.highOffset
        )

        // Update the events ranges
        existingMessage.eventsRange.start = Math.min(existingMessage.eventsRange.start, parsedMessage.eventsRange.start)
        existingMessage.eventsRange.end = Math.max(existingMessage.eventsRange.end, parsedMessage.eventsRange.end)
    }

    return {
        sessions: Array.from(parsedSessions.values()),
        partitionStats: Array.from(lastMessageForPartition.values()), // Just cast the last message into the small BatchStats interface
    }
}

export const convertForPersistence = (
    messages: IncomingRecordingMessage['eventsByWindowId']
): PersistedRecordingMessage[] => {
    return Object.entries(messages).map(([window_id, events]) => {
        return {
            window_id,
            data: events,
        }
    })
}

export const allSettledWithConcurrency = async <T, Q>(
    concurrency: number,
    arr: T[],
    fn: (item: T, context: { index: number; break: () => void }) => Promise<Q>
): Promise<{ error?: any; result?: Q }[]> => {
    // This function processes promises in parallel like Promise.allSettled, but with a maximum concurrency

    let breakCalled = false

    return new Promise<{ error?: any; result?: Q }[]>((resolve) => {
        const results: { error?: any; result?: Q }[] = []
        const remaining = [...arr]
        let runningCount = 0

        const run = () => {
            while (remaining.length && runningCount < concurrency) {
                if (breakCalled) {
                    return
                }
                const item = remaining.shift()
                if (item) {
                    const arrIndex = arr.indexOf(item)
                    runningCount += 1
                    fn(item, {
                        index: arrIndex,
                        break: () => {
                            breakCalled = true
                            return resolve(results)
                        },
                    })
                        .then((result) => {
                            results[arrIndex] = { result: result }
                        })
                        .catch((err) => {
                            results[arrIndex] = { error: err }
                        })
                        .finally(() => {
                            runningCount -= 1
                            run()
                        })
                }
            }

            if (remaining.length === 0 && !runningCount) {
                return !breakCalled ? resolve(results) : undefined
            }
        }

        run()
    })
}
