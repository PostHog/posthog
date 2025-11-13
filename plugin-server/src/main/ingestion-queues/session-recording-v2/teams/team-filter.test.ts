import { DateTime } from 'luxon'

import { ParsedMessageData } from '../kafka/types'
import { TeamFilter } from './team-filter'
import { TeamService } from './team-service'
import { TeamForReplay } from './types'

jest.mock('./team-service')

const validTeam: TeamForReplay = {
    teamId: 1,
    consoleLogIngestionEnabled: true,
}

const createMessage = (token?: string, overrides = {}): ParsedMessageData => ({
    metadata: {
        partition: 0,
        topic: 'test',
        offset: 0,
        timestamp: Date.now(),
        rawSize: 100,
    },
    headers: token ? [{ token }] : undefined,
    distinct_id: 'distinct_id',
    session_id: 'session_id',
    eventsByWindowId: {},
    eventsRange: {
        start: DateTime.fromMillis(0),
        end: DateTime.fromMillis(0),
    },
    snapshot_source: null,
    snapshot_library: null,
    ...overrides,
})

describe('TeamFilter', () => {
    let teamFilter: TeamFilter
    let mockTeamService: jest.Mocked<TeamService>

    beforeEach(() => {
        jest.clearAllMocks()
        mockTeamService = {
            getTeamByToken: jest.fn(),
            getRetentionPeriodByTeamId: jest.fn(),
        } as unknown as jest.Mocked<TeamService>
        teamFilter = new TeamFilter(mockTeamService)
    })

    describe('team token validation', () => {
        it('processes messages with valid team token', async () => {
            const message = createMessage('valid-token')
            mockTeamService.getTeamByToken.mockResolvedValueOnce(validTeam)
            mockTeamService.getRetentionPeriodByTeamId.mockResolvedValueOnce('90d')

            const result = await teamFilter.filterBatch([message])

            expect(result).toEqual([{ team: validTeam, message: message }])
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('valid-token')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(1)
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledTimes(1)
        })

        it('drops messages with no token in header', async () => {
            const message = createMessage()
            const result = await teamFilter.filterBatch([message])

            expect(result).toEqual([])
            expect(mockTeamService.getTeamByToken).not.toHaveBeenCalled()
        })

        it('drops messages with invalid team tokens', async () => {
            const message = createMessage('invalid-token')
            mockTeamService.getTeamByToken.mockResolvedValueOnce(null)

            const result = await teamFilter.filterBatch([message])

            expect(result).toEqual([])
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('invalid-token')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(1)
        })

        it('drops messages with team missing retention period', async () => {
            const message = createMessage('valid-token')
            mockTeamService.getTeamByToken.mockResolvedValueOnce(validTeam)
            mockTeamService.getRetentionPeriodByTeamId.mockResolvedValueOnce(null)

            const result = await teamFilter.filterBatch([message])

            expect(result).toEqual([])
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('valid-token')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(1)
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledTimes(1)
        })
    })

    describe('batch processing', () => {
        it('processes multiple messages in order', async () => {
            const timestamp = Date.now()
            const messages = [
                createMessage('token1', { metadata: { timestamp } }),
                createMessage('token2', { metadata: { timestamp: timestamp + 1 } }),
            ]

            mockTeamService.getTeamByToken.mockResolvedValue(validTeam)
            mockTeamService.getRetentionPeriodByTeamId.mockResolvedValue('90d')

            const result = await teamFilter.filterBatch(messages)

            expect(result).toEqual([
                { team: validTeam, message: messages[0] },
                { team: validTeam, message: messages[1] },
            ])
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('token1')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('token2')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(2)
        })

        it('processes messages with different teams', async () => {
            const timestamp = Date.now()
            const messages = [
                createMessage('token1', { metadata: { timestamp } }),
                createMessage('token2', { metadata: { timestamp: timestamp + 1 } }),
            ]

            const team2 = { ...validTeam, teamId: 2 }
            mockTeamService.getTeamByToken.mockResolvedValueOnce(validTeam).mockResolvedValueOnce(team2)
            mockTeamService.getRetentionPeriodByTeamId.mockResolvedValue('90d')

            const result = await teamFilter.filterBatch(messages)

            expect(result).toEqual([
                { team: validTeam, message: messages[0] },
                { team: team2, message: messages[1] },
            ])
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('token1')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('token2')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(2)
        })

        it('handles mixed valid and invalid messages in batch', async () => {
            const messages = [
                createMessage('token1'),
                createMessage(), // No token
                createMessage('token2'),
            ]

            mockTeamService.getTeamByToken.mockResolvedValue(validTeam)
            mockTeamService.getRetentionPeriodByTeamId.mockResolvedValue('90d')

            const result = await teamFilter.filterBatch(messages)

            expect(result).toEqual([
                { team: validTeam, message: messages[0] },
                { team: validTeam, message: messages[2] },
            ])
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('token1')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledWith('token2')
            expect(mockTeamService.getTeamByToken).toHaveBeenCalledTimes(2)
        })
    })
})
