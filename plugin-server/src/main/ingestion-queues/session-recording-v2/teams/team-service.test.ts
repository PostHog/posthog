import { PostgresRouter } from '../../../../utils/db/postgres'
import { fetchTeamTokensWithRecordings } from '../../../../worker/ingestion/team-manager'
import { TeamService } from './team-service'

jest.mock('~/src/worker/ingestion/team-manager')
const mockFetchTeamTokens = fetchTeamTokensWithRecordings as jest.MockedFunction<typeof fetchTeamTokensWithRecordings>

describe('TeamService', () => {
    let teamService: TeamService
    let mockPostgres: jest.Mocked<PostgresRouter>

    beforeEach(() => {
        jest.useFakeTimers()
        mockPostgres = {} as jest.Mocked<PostgresRouter>
        mockFetchTeamTokens.mockReset()

        // Default mock implementation
        mockFetchTeamTokens.mockResolvedValue({
            'valid-token': { teamId: 1, consoleLogIngestionEnabled: true },
            'valid-token-2': { teamId: 2, consoleLogIngestionEnabled: false },
        })

        teamService = new TeamService(mockPostgres)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('getTeamByToken', () => {
        it('should return team for valid token', async () => {
            const team = await teamService.getTeamByToken('valid-token')
            expect(team).toEqual({
                teamId: 1,
                consoleLogIngestionEnabled: true,
            })
        })

        it('should return null for invalid token', async () => {
            const team = await teamService.getTeamByToken('invalid-token')
            expect(team).toBeNull()
        })

        it('should return null if teamId is missing', async () => {
            mockFetchTeamTokens.mockResolvedValue({
                token: { teamId: null as any, consoleLogIngestionEnabled: true },
            })
            const team = await teamService.getTeamByToken('token')
            expect(team).toBeNull()
        })

        it('should cache results and not fetch again within refresh period', async () => {
            await teamService.getTeamByToken('valid-token')
            await teamService.getTeamByToken('valid-token-2')

            // Advance time but not enough to trigger refresh
            jest.advanceTimersByTime(4 * 60 * 1000) // 4 minutes (refresh is 5 minutes)

            await teamService.getTeamByToken('valid-token')
            await teamService.getTeamByToken('valid-token-2')

            expect(mockFetchTeamTokens).toHaveBeenCalledTimes(1)
        })

        it('should refresh after max age', async () => {
            await teamService.getTeamByToken('valid-token')
            expect(mockFetchTeamTokens).toHaveBeenCalledTimes(1)

            // Move time forward past the refresh interval
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // This should trigger a refresh
            await teamService.getTeamByToken('valid-token')
            expect(mockFetchTeamTokens).toHaveBeenCalledTimes(2)
        })

        it('should handle refresh errors and return cached data', async () => {
            // First call succeeds
            await teamService.getTeamByToken('valid-token')
            expect(mockFetchTeamTokens).toHaveBeenCalledTimes(1)

            // Make next refresh fail
            mockFetchTeamTokens.mockRejectedValueOnce(new Error('Refresh failed'))

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Should still return cached data
            const team = await teamService.getTeamByToken('valid-token')
            expect(team).toEqual({
                teamId: 1,
                consoleLogIngestionEnabled: true,
            })
        })

        it('should eventually update cache after successful refresh', async () => {
            // Initial fetch
            const team1 = await teamService.getTeamByToken('valid-token')
            expect(team1?.consoleLogIngestionEnabled).toBe(true)

            // Update mock data and capture the promise
            const mockFetchPromise = Promise.resolve({
                'valid-token': { teamId: 1, consoleLogIngestionEnabled: false },
            })
            mockFetchTeamTokens.mockReturnValue(mockFetchPromise)

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Wait for the new value to appear using a spinlock, don't advance time though
            while ((await teamService.getTeamByToken('valid-token'))?.consoleLogIngestionEnabled !== false) {
                await Promise.resolve() // Allow other promises to resolve
            }

            const team2 = await teamService.getTeamByToken('valid-token')
            expect(team2?.consoleLogIngestionEnabled).toBe(false)
        })

        it('should eventually return null when team is removed after refresh', async () => {
            // Initial fetch
            const team1 = await teamService.getTeamByToken('valid-token')
            expect(team1?.teamId).toBe(1)

            // Update mock data to remove the team
            const mockFetchPromise = Promise.resolve({
                'valid-token-2': { teamId: 2, consoleLogIngestionEnabled: false }, // Remove valid-token
            })
            mockFetchTeamTokens.mockReturnValue(mockFetchPromise)

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Wait for the team to be removed using a spinlock, don't advance time though
            while ((await teamService.getTeamByToken('valid-token')) !== null) {
                await Promise.resolve() // Allow other promises to resolve
            }

            const team2 = await teamService.getTeamByToken('valid-token')
            expect(team2).toBeNull()
        })
    })
})
