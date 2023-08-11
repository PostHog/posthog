import { Settings } from 'luxon'

import { defaultConfig } from '../../../src/config/config'
import { PostgresRouter, PostgresUse } from '../../../src/utils/db/postgres'
import { TeamManager } from '../../../src/worker/ingestion/team-manager'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')
jest.mock('../../../src/utils/posthog', () => ({
    posthog: {
        identify: jest.fn(),
        capture: jest.fn(),
    },
}))

describe('TeamManager()', () => {
    let teamManager: TeamManager
    let postgres: PostgresRouter

    beforeEach(async () => {
        await resetTestDatabase()
        postgres = new PostgresRouter(defaultConfig, undefined)
        teamManager = new TeamManager(postgres, defaultConfig)
        Settings.defaultZoneName = 'utc'
    })

    afterEach(async () => {
        await postgres.end()
    })

    describe('fetchTeam()', () => {
        it('fetches and caches the team', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:05Z').getTime())
            jest.spyOn(postgres, 'query')

            let team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')

            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:55Z').getTime())
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                "UPDATE posthog_team SET name = 'Updated Name!'",
                undefined,
                'testTag'
            )

            jest.mocked(postgres.query).mockClear()

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('TEST PROJECT')
            // expect(team!.__fetch_event_uuid).toEqual('uuid1')
            expect(postgres.query).toHaveBeenCalledTimes(0)

            // 2min have passed i.e. the cache should have expired
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:02:06Z').getTime())

            team = await teamManager.fetchTeam(2)
            expect(team!.name).toEqual('Updated Name!')

            expect(postgres.query).toHaveBeenCalledTimes(1)
        })

        it('returns null when no such team', async () => {
            expect(await teamManager.fetchTeam(-1)).toEqual(null)
        })
    })

    describe('getTeamByToken()', () => {
        it('caches positive lookups for 2 minutes', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:05Z').getTime())
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                "UPDATE posthog_team SET api_token = 'my_token'",
                undefined,
                'testTag'
            )

            // Initial lookup hits the DB and returns null
            jest.spyOn(postgres, 'query')
            let team = await teamManager.getTeamByToken('my_token')
            expect(postgres.query).toHaveBeenCalledTimes(1)
            expect(team!.id).toEqual(2)
            expect(team!.anonymize_ips).toEqual(false)

            // Settings are updated
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                'UPDATE posthog_team SET anonymize_ips = true',
                undefined,
                'testTag'
            )

            // Second lookup hits the cache and skips the DB lookup, setting is stale
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:01:56Z').getTime())
            jest.mocked(postgres.query).mockClear()
            team = await teamManager.getTeamByToken('my_token')
            expect(postgres.query).toHaveBeenCalledTimes(0)
            expect(team!.id).toEqual(2)
            expect(team!.anonymize_ips).toEqual(false)

            // Setting change take effect after cache expiration
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:25:06Z').getTime())
            jest.mocked(postgres.query).mockClear()
            team = await teamManager.getTeamByToken('my_token')
            expect(postgres.query).toHaveBeenCalledTimes(1)
            expect(team!.id).toEqual(2)
            expect(team!.anonymize_ips).toEqual(true)
        })

        it('caches negative lookups for 5 minutes', async () => {
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:00:05Z').getTime())

            // Initial lookup hits the DB and returns null
            jest.spyOn(postgres, 'query')
            expect(await teamManager.getTeamByToken('unknown')).toEqual(null)
            expect(postgres.query).toHaveBeenCalledTimes(1)

            // Second lookup hits the cache and skips the DB lookup
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:03:06Z').getTime())
            jest.mocked(postgres.query).mockClear()
            expect(await teamManager.getTeamByToken('unknown')).toEqual(null)
            expect(postgres.query).toHaveBeenCalledTimes(0)

            // Hit the DB on cache expiration
            jest.spyOn(global.Date, 'now').mockImplementation(() => new Date('2020-02-27T11:05:06Z').getTime())
            jest.mocked(postgres.query).mockClear()
            expect(await teamManager.getTeamByToken('unknown')).toEqual(null)
            expect(postgres.query).toHaveBeenCalledTimes(1)
        })

        it('throws on postgres errors', async () => {
            postgres.query = jest.fn().mockRejectedValue(new Error('PG unavailable'))
            await expect(async () => {
                await teamManager.getTeamByToken('another')
            }).rejects.toThrow('PG unavailable')
        })
    })
})
