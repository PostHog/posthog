import { MessageHeader } from 'node-rdkafka'

import { logger } from '../../../../utils/logger'
import { eventDroppedCounter } from '../../metrics'
import { ParsedMessageData } from '../kafka/types'
import { TeamService } from './team-service'
import { MessageWithTeam, TeamForReplay } from './types'

export class TeamFilter {
    constructor(private readonly teamService: TeamService) {}

    public async filterBatch(messages: ParsedMessageData[]): Promise<MessageWithTeam[]> {
        const messagesWithTeam: MessageWithTeam[] = []

        for (const message of messages) {
            const team = await this.validateTeam(message)
            if (team) {
                messagesWithTeam.push({
                    team,
                    message: message,
                })
            }
        }

        return messagesWithTeam
    }

    private async validateTeam(message: ParsedMessageData): Promise<TeamForReplay | null> {
        const dropMessage = (reason: string, extra?: Record<string, any>) => {
            // TODO refactor
            eventDroppedCounter
                .labels({
                    event_type: 'session_recordings_blob_ingestion_v2',
                    drop_cause: reason,
                })
                .inc()

            logger.warn('⚠️', 'invalid_message', {
                reason,
                partition: message.metadata.partition,
                offset: message.metadata.offset,
                ...(extra || {}),
            })
        }

        const { token, team } = await this.readTokenFromHeaders(message.headers)

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
