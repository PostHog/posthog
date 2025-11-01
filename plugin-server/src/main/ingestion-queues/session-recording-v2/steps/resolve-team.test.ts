import { dlq, drop, isDlqResult, isDropResult, isOkResult, ok } from '../../../../ingestion/pipelines/results'
import { EventHeaders } from '../../../../types'
import { ParsedMessageData } from '../kafka/types'
import { TeamService } from '../teams/team-service'
import { TeamForReplay } from '../teams/types'
import { createTestMessage } from '../test-helpers'
import { createResolveTeamStep } from './resolve-team'

describe('resolve-team', () => {
    const mockTeamService = {
        getTeamByToken: jest.fn(),
        getRetentionPeriodByTeamId: jest.fn(),
    } as unknown as TeamService

    beforeEach(() => {
        jest.clearAllMocks()
    })

    const createInput = (token?: string) => {
        const message = createTestMessage()
        const headers = {
            token: token || 'test-token',
            distinct_id: 'user-123',
            force_disable_person_processing: false,
        }
        const parsedMessage = {
            metadata: {
                partition: 0,
                topic: 'test-topic',
                rawSize: 1024,
                offset: 0,
                timestamp: 1672527600000,
            },
            headers: [],
            distinct_id: 'user-123',
            session_id: 'session-123',
            eventsByWindowId: {},
            eventsRange: { start: null as any, end: null as any },
            snapshot_source: null,
            snapshot_library: null,
        }

        return { message, headers, parsedMessage }
    }

    const createTeam = (teamId: number): TeamForReplay => ({
        teamId,
        consoleLogIngestionEnabled: true,
    })

    it('should return ok with team when token is valid and team has retention', async () => {
        const step = createResolveTeamStep(mockTeamService)
        const input = createInput('valid-token')
        const team = createTeam(123)

        ;(mockTeamService.getTeamByToken as jest.Mock).mockResolvedValue(team)
        ;(mockTeamService.getRetentionPeriodByTeamId as jest.Mock).mockResolvedValue(90)

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        expect(result).toEqual(
            ok({
                message: input.message,
                headers: input.headers,
                parsedMessage: input.parsedMessage,
                team,
            })
        )
        expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('valid-token')
        expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(123)
    })

    it('should return dlq when token is missing', async () => {
        const step = createResolveTeamStep(mockTeamService)
        const input = createInput()
        input.headers.token = undefined as any

        const result = await step(input)

        expect(isDlqResult(result)).toBe(true)
        expect(result).toEqual(dlq('no_token_in_header'))
        expect(mockTeamService.getTeamByToken).not.toHaveBeenCalled()
    })

    it('should return drop when team is not found', async () => {
        const step = createResolveTeamStep(mockTeamService)
        const input = createInput('invalid-token')

        ;(mockTeamService.getTeamByToken as jest.Mock).mockResolvedValue(null)

        const result = await step(input)

        expect(isDropResult(result)).toBe(true)
        expect(result).toEqual(drop('header_token_present_team_missing_or_disabled'))
        expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('invalid-token')
        expect(mockTeamService.getRetentionPeriodByTeamId).not.toHaveBeenCalled()
    })

    it('should return drop when team has no retention period', async () => {
        const step = createResolveTeamStep(mockTeamService)
        const input = createInput('valid-token')
        const team = createTeam(456)

        ;(mockTeamService.getTeamByToken as jest.Mock).mockResolvedValue(team)
        ;(mockTeamService.getRetentionPeriodByTeamId as jest.Mock).mockResolvedValue(null)

        const result = await step(input)

        expect(isDropResult(result)).toBe(true)
        expect(result).toEqual(drop('team_missing_retention_period'))
        expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('valid-token')
        expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(456)
    })

    it('should return drop when retention period is 0', async () => {
        const step = createResolveTeamStep(mockTeamService)
        const input = createInput('valid-token')
        const team = createTeam(789)

        ;(mockTeamService.getTeamByToken as jest.Mock).mockResolvedValue(team)
        ;(mockTeamService.getRetentionPeriodByTeamId as jest.Mock).mockResolvedValue(0)

        const result = await step(input)

        expect(isDropResult(result)).toBe(true)
        expect(result).toEqual(drop('team_missing_retention_period'))
    })

    it('should preserve generic input properties not specified in Input type', async () => {
        const step = createResolveTeamStep<{
            headers: EventHeaders
            parsedMessage: ParsedMessageData
            customField: string
            anotherField: number
        }>(mockTeamService)
        const team = { teamId: 1, consoleLogIngestionEnabled: false }
        const baseInput = createInput('test-token')
        const input = { ...baseInput, customField: 'test-value', anotherField: 123 }

        ;(mockTeamService.getTeamByToken as jest.Mock).mockResolvedValue(team)
        ;(mockTeamService.getRetentionPeriodByTeamId as jest.Mock).mockResolvedValue(30)

        const result = await step(input)

        expect(isOkResult(result)).toBe(true)
        if (isOkResult(result)) {
            expect(result.value).toMatchObject({
                headers: baseInput.headers,
                parsedMessage: baseInput.parsedMessage,
                customField: 'test-value',
                anotherField: 123,
                team,
            })
        }
    })
})
