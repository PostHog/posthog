import { promisify } from 'node:util'
const { unzip } = require('node:zlib')
import { Message, MessageHeader } from 'node-rdkafka'

import { PipelineEvent, RawEventMessage, RRWebEvent } from '../../../../types'
import { KafkaProducerWrapper } from '../../../../utils/db/kafka-producer-wrapper'
import { status } from '../../../../utils/status'
import { captureIngestionWarning } from '../../../../worker/ingestion/utils'
import { eventDroppedCounter } from '../../metrics'
import { TeamIDWithConfig } from '../consumer'
import { IncomingRecordingMessage, ParsedBatch } from '../types'
import { KafkaMetrics } from './metrics'

const GZIP_HEADER = Buffer.from([0x1f, 0x8b, 0x08, 0x00])
const do_unzip = promisify(unzip)

export class KafkaParser {
    constructor(private readonly metrics: KafkaMetrics) {}

    public async parseMessage(
        message: Message,
        getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>,
        ingestionWarningProducer: KafkaProducerWrapper | undefined
    ): Promise<IncomingRecordingMessage | void> {
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
            return dropMessage('message_value_or_timestamp_is_empty')
        }

        const headerResult = await this.readTokenFromHeaders(message.headers, getTeamFn)
        const token: string | undefined = headerResult.token
        const teamIdWithConfig: null | TeamIDWithConfig = headerResult.teamIdWithConfig

        if (!token) {
            return dropMessage('no_token_in_header')
        }

        if (teamIdWithConfig == null || teamIdWithConfig.teamId == null) {
            return dropMessage('header_token_present_team_missing_or_disabled', {
                token: token,
            })
        }

        if (!!ingestionWarningProducer && !!teamIdWithConfig.teamId) {
            const libVersion = this.readLibVersionFromHeaders(message.headers)
            const parsedVersion = this.parseVersion(libVersion)
            if (parsedVersion && parsedVersion.major === 1 && parsedVersion.minor < 75) {
                this.metrics.incrementLibVersionWarning()

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
            if (this.isGzipped(message.value)) {
                messageUnzipped = await do_unzip(message.value)
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

    public async parseBatch(messages: Message[]): Promise<ParsedBatch> {
        const lastMessageForPartition: Map<number, Message> = new Map()
        const parsedSessions: Map<string, IncomingRecordingMessage> = new Map()

        for (const message of messages) {
            const partition = message.partition
            lastMessageForPartition.set(partition, message)
            this.metrics.incrementMessageReceived(partition)

            const getTeamFn = (_: string) => Promise.resolve(null)
            const parsedMessage = await this.parseMessage(message, getTeamFn, undefined)
            if (!parsedMessage) {
                continue
            }

            const sessionKey = `${parsedMessage.team_id}:${parsedMessage.session_id}`
            const existingMessage = parsedSessions.get(sessionKey)

            if (existingMessage === undefined) {
                parsedSessions.set(sessionKey, parsedMessage)
                continue
            }

            for (const [windowId, events] of Object.entries(parsedMessage.eventsByWindowId)) {
                existingMessage.eventsByWindowId[windowId] = (existingMessage.eventsByWindowId[windowId] || []).concat(
                    events
                )
            }

            existingMessage.metadata.rawSize += parsedMessage.metadata.rawSize
            existingMessage.metadata.lowOffset = Math.min(
                existingMessage.metadata.lowOffset,
                parsedMessage.metadata.lowOffset
            )
            existingMessage.metadata.highOffset = Math.max(
                existingMessage.metadata.highOffset,
                parsedMessage.metadata.highOffset
            )
            existingMessage.eventsRange.start = Math.min(
                existingMessage.eventsRange.start,
                parsedMessage.eventsRange.start
            )
            existingMessage.eventsRange.end = Math.max(existingMessage.eventsRange.end, parsedMessage.eventsRange.end)
        }

        return {
            sessions: Array.from(parsedSessions.values()),
            partitionStats: Array.from(lastMessageForPartition.values()),
        }
    }

    private isGzipped(buffer: Buffer): boolean {
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

    private async readTokenFromHeaders(
        headers: MessageHeader[] | undefined,
        getTeamFn: (s: string) => Promise<TeamIDWithConfig | null>
    ) {
        const tokenHeader = headers?.find((header: MessageHeader) => header.token)?.token
        const token = typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()
        const teamIdWithConfig = token ? await getTeamFn(token) : null
        return { token, teamIdWithConfig }
    }

    private readLibVersionFromHeaders(headers: MessageHeader[] | undefined): string | undefined {
        const libVersionHeader = headers?.find((header) => header['lib_version'])?.['lib_version']
        return typeof libVersionHeader === 'string' ? libVersionHeader : libVersionHeader?.toString()
    }

    private parseVersion(libVersion: string | undefined) {
        try {
            let majorString: string | undefined = undefined
            let minorString: string | undefined = undefined
            if (libVersion && libVersion.includes('.')) {
                const splat = libVersion.split('.')
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
}
