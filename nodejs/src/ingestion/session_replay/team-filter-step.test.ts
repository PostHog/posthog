import { DateTime } from 'luxon'

import { ParsedMessageData } from '../../session-recording/kafka/types'
import { TeamForReplay } from '../../session-recording/teams/types'
import { TeamService } from '../../session-replay/shared/teams/team-service'
import { PipelineResultType } from '../pipelines/results'
import { ParseMessageStepOutput } from './parse-message-step'
import { createTeamFilterStep } from './team-filter-step'

describe('createTeamFilterStep', () => {
    const createParsedMessage = (sessionId: string, token: string | null = 'test-token'): ParsedMessageData => ({
        metadata: {
            partition: 0,
            topic: 'test-topic',
            offset: 1,
            timestamp: 1234567890,
            rawSize: 100,
        },
        headers: token ? [{ token: Buffer.from(token) }] : [],
        distinct_id: 'distinct_id',
        session_id: sessionId,
        token,
        eventsByWindowId: { window1: [] },
        eventsRange: { start: DateTime.fromMillis(0), end: DateTime.fromMillis(0) },
        snapshot_source: null,
        snapshot_library: null,
    })

    const createInput = (sessionId: string, token: string | null = 'test-token'): ParseMessageStepOutput => ({
        parsedMessage: createParsedMessage(sessionId, token),
    })

    const defaultTeam: TeamForReplay = {
        teamId: 1,
        consoleLogIngestionEnabled: false,
    }

    it('should enrich message with team context when team is valid', async () => {
        const mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(defaultTeam),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        const step = createTeamFilterStep(mockTeamService)
        const input = createInput('session-1')

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.team.teamId).toBe(1)
            expect(result.value.parsedMessage.session_id).toBe('session-1')
        }
    })

    it('should DLQ message when token is missing', async () => {
        const mockTeamService = {
            getTeamByToken: jest.fn(),
            getRetentionPeriodByTeamId: jest.fn(),
        } as unknown as TeamService

        const step = createTeamFilterStep(mockTeamService)
        const input = createInput('session-1', null)

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DLQ)
        if (result.type === PipelineResultType.DLQ) {
            expect(result.reason).toBe('no_token_in_header')
        }
        expect(mockTeamService.getTeamByToken).not.toHaveBeenCalled()
    })

    it('should drop message when team is not found', async () => {
        const mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(null),
            getRetentionPeriodByTeamId: jest.fn(),
        } as unknown as TeamService

        const step = createTeamFilterStep(mockTeamService)
        const input = createInput('session-1')

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('header_token_present_team_missing_or_disabled')
        }
        expect(mockTeamService.getRetentionPeriodByTeamId).not.toHaveBeenCalled()
    })

    it('should drop message when retention period is missing', async () => {
        const mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(defaultTeam),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(null),
        } as unknown as TeamService

        const step = createTeamFilterStep(mockTeamService)
        const input = createInput('session-1')

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.DROP)
        if (result.type === PipelineResultType.DROP) {
            expect(result.reason).toBe('team_missing_retention_period')
        }
    })

    it('should call teamService methods with correct arguments', async () => {
        const mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(defaultTeam),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        const step = createTeamFilterStep(mockTeamService)
        const input = createInput('my-session', 'my-token')

        await step(input)

        expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(1)
        expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('my-token')
        expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledTimes(1)
        expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(1)
    })

    it('should preserve parsed message data in the output', async () => {
        const mockTeamService = {
            getTeamByToken: jest.fn().mockResolvedValue(defaultTeam),
            getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
        } as unknown as TeamService

        const step = createTeamFilterStep(mockTeamService)
        const input = createInput('my-session', 'my-token')

        const result = await step(input)

        expect(result.type).toBe(PipelineResultType.OK)
        if (result.type === PipelineResultType.OK) {
            expect(result.value.parsedMessage).toBe(input.parsedMessage)
            expect(result.value.parsedMessage.session_id).toBe('my-session')
            expect(result.value.parsedMessage.token).toBe('my-token')
        }
    })
})
