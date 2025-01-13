import { Message, MessageHeader } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../../../utils/db/kafka-producer-wrapper'
import { status } from '../../../../utils/status'
import { captureIngestionWarning } from '../../../../worker/ingestion/utils'
import { eventDroppedCounter } from '../../metrics'
import { KafkaMetrics } from '../kafka/metrics'
import { KafkaParser } from '../kafka/parser'
import { TeamManager } from './team-manager'
import { MessageWithTeam, Team } from './types'

export class TeamFilter {
    constructor(
        private readonly teamManager: TeamManager,
        private readonly metrics: KafkaMetrics,
        private readonly parser: KafkaParser
    ) {}

    public async parseMessage(
        message: Message,
        ingestionWarningProducer: KafkaProducerWrapper | undefined
    ): Promise<MessageWithTeam | null> {
        const team = await this.validateTeamToken(message, message.headers, ingestionWarningProducer)
        if (!team) {
            return null
        }

        const parsedMessage = await this.parser.parseMessage(message)
        if (!parsedMessage) {
            return null
        }

        return {
            team,
            message: parsedMessage,
        }
    }

    public async parseBatch(messages: Message[]): Promise<MessageWithTeam[]> {
        const parsedMessages: MessageWithTeam[] = []

        for (const message of messages) {
            const messageWithTeam = await this.parseMessage(message, undefined)
            if (messageWithTeam) {
                parsedMessages.push(messageWithTeam)
            }
        }

        return parsedMessages
    }

    private async validateTeamToken(
        message: Message,
        headers: MessageHeader[] | undefined,
        ingestionWarningProducer: KafkaProducerWrapper | undefined
    ): Promise<Team | null> {
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

        const { token, team } = await this.readTokenFromHeaders(headers)

        if (!token) {
            dropMessage('no_token_in_header')
            return null
        }

        if (!team) {
            dropMessage('header_token_present_team_missing_or_disabled', {
                token: token,
            })
            return null
        }

        if (!!ingestionWarningProducer) {
            const libVersion = this.readLibVersionFromHeaders(headers)
            const parsedVersion = this.parseVersion(libVersion)
            if (parsedVersion && parsedVersion.major === 1 && parsedVersion.minor < 75) {
                this.metrics.incrementLibVersionWarning()

                await captureIngestionWarning(
                    ingestionWarningProducer,
                    team.teamId,
                    'replay_lib_version_too_old',
                    {
                        libVersion,
                        parsedVersion,
                    },
                    { key: libVersion || 'unknown' }
                )
            }
        }

        return team
    }

    private async readTokenFromHeaders(headers: MessageHeader[] | undefined) {
        const tokenHeader = headers?.find((header: MessageHeader) => header.token)?.token
        const token = typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()
        const team = token ? await this.teamManager.getTeamByToken(token) : null
        return { token, team }
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
