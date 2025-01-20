import { Message, MessageHeader } from 'node-rdkafka'

import { status } from '../../../../utils/status'
import { eventDroppedCounter } from '../../metrics'
import { KafkaParser } from '../kafka/parser'
import { BatchMessageProcessor } from '../types'
import { TeamService } from './team-service'
import { MessageWithTeam, Team } from './types'

export class TeamFilter implements BatchMessageProcessor<Message, MessageWithTeam> {
    constructor(private readonly teamService: TeamService, private readonly parser: KafkaParser) {}

    public async parseMessage(message: Message): Promise<MessageWithTeam | null> {
        const team = await this.validateTeamToken(message, message.headers)
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
            const messageWithTeam = await this.parseMessage(message)
            if (messageWithTeam) {
                parsedMessages.push(messageWithTeam)
            }
        }

        return parsedMessages
    }

    private async validateTeamToken(message: Message, headers: MessageHeader[] | undefined): Promise<Team | null> {
        const dropMessage = (reason: string, extra?: Record<string, any>) => {
            // TODO refactor
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

        return team
    }

    private async readTokenFromHeaders(headers: MessageHeader[] | undefined) {
        const tokenHeader = headers?.find((header: MessageHeader) => header.token)?.token
        const token = typeof tokenHeader === 'string' ? tokenHeader : tokenHeader?.toString()
        const team = token ? await this.teamService.getTeamByToken(token) : null
        return { token, team }
    }
}
