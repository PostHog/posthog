import { PostgresRouter } from '../../../utils/db/postgres'
import { TeamService } from './team-service'

describe('TeamService', () => {
    let teamService: TeamService
    let fetchSpy: jest.SpyInstance

    beforeEach(() => {
        jest.useFakeTimers()
        const mockPostgres = {} as jest.Mocked<PostgresRouter>
        teamService = new TeamService(mockPostgres)

        fetchSpy = jest.spyOn(teamService as any, 'fetchTeamTokensWithRecordings').mockResolvedValue({
            tokenMap: {
                'valid-token': { teamId: 1, consoleLogIngestionEnabled: true },
                'valid-token-2': { teamId: 2, consoleLogIngestionEnabled: false },
            },
            retentionMap: { 1: '30d', 2: '1y' },
            encryptionMap: { 1: true, 2: false },
        })
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
            fetchSpy.mockResolvedValue({
                tokenMap: {
                    token: { teamId: null as any, consoleLogIngestionEnabled: true },
                },
                retentionMap: { 1: '30d', 2: '1y' },
                encryptionMap: { 1: true, 2: false },
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

            expect(fetchSpy).toHaveBeenCalledTimes(1)
        })

        it('should refresh after max age', async () => {
            await teamService.getTeamByToken('valid-token')
            expect(fetchSpy).toHaveBeenCalledTimes(1)

            // Move time forward past the refresh interval
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // This should trigger a refresh
            await teamService.getTeamByToken('valid-token')
            expect(fetchSpy).toHaveBeenCalledTimes(2)
        })

        it('should handle refresh errors and return cached data', async () => {
            // First call succeeds
            await teamService.getTeamByToken('valid-token')
            expect(fetchSpy).toHaveBeenCalledTimes(1)

            // Make next refresh fail
            fetchSpy.mockRejectedValueOnce(new Error('Refresh failed'))

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
                tokenMap: {
                    'valid-token': { teamId: 1, consoleLogIngestionEnabled: false },
                },
                retentionMap: { 1: '30d', 2: '1y' },
                encryptionMap: { 1: true, 2: false },
            })
            fetchSpy.mockReturnValue(mockFetchPromise)

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
                tokenMap: {
                    'valid-token-2': { teamId: 2, consoleLogIngestionEnabled: false }, // Remove valid-token
                },
                retentionMap: { 2: '1y' },
                encryptionMap: { 2: false },
            })
            fetchSpy.mockReturnValue(mockFetchPromise)

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

    describe('getRetentionPeriodByTeamId', () => {
        it('should return retention period for known team', async () => {
            const retention = await teamService.getRetentionPeriodByTeamId(1)
            expect(retention).toBe('30d')
        })

        it('should return different retention periods per team', async () => {
            const retention1 = await teamService.getRetentionPeriodByTeamId(1)
            const retention2 = await teamService.getRetentionPeriodByTeamId(2)
            expect(retention1).toBe('30d')
            expect(retention2).toBe('1y')
        })

        it('should return null for unknown team', async () => {
            const retention = await teamService.getRetentionPeriodByTeamId(999)
            expect(retention).toBeNull()
        })
    })

    describe('getEncryptionEnabledByTeamId', () => {
        it('should return true for team with encryption enabled', async () => {
            const enabled = await teamService.getEncryptionEnabledByTeamId(1)
            expect(enabled).toBe(true)
        })

        it('should return false for team with encryption disabled', async () => {
            const enabled = await teamService.getEncryptionEnabledByTeamId(2)
            expect(enabled).toBe(false)
        })

        it('should return false for unknown team', async () => {
            const enabled = await teamService.getEncryptionEnabledByTeamId(999)
            expect(enabled).toBe(false)
        })
    })
})
