import { Settings } from 'luxon'

import { forSnapshot } from '~/tests/helpers/snapshots'

import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { TeamManager } from './team-manager'

describe('TeamManager()', () => {
    let hub: Hub
    let teamManager: TeamManager
    let postgres: PostgresRouter
    let teamId: Team['id']
    let fetchTeamsSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        teamManager = new TeamManager(postgres)
        teamId = (await getFirstTeam(hub)).id
        fetchTeamsSpy = jest.spyOn(teamManager as any, 'fetchTeams')
        // // @ts-expect-error TODO: Fix underlying settings, is this really working?
        // Settings.defaultZoneName = 'utc'
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('getTeam()', () => {
        it('returns the team', async () => {
            const result = await teamManager.getTeam(teamId)
            // This one test is a snapshot to ensure the team object is stable
            expect(forSnapshot(result)).toMatchInlineSnapshot(`
                {
                  "anonymize_ips": false,
                  "api_token": "THIS IS NOT A TOKEN FOR TEAM 2",
                  "available_features": [],
                  "cookieless_server_hash_mode": null,
                  "heatmaps_opt_in": null,
                  "id": 2,
                  "ingested_event": true,
                  "name": "TEST PROJECT",
                  "organization_id": "<REPLACED-UUID-1>",
                  "person_display_name_properties": [],
                  "person_processing_opt_out": null,
                  "project_id": 2,
                  "session_recording_opt_in": true,
                  "slack_incoming_webhook": null,
                  "timezone": "UTC",
                  "uuid": "<REPLACED-UUID-0>",
                }
            `)
        })

        it('returns null if the team does not exist', async () => {
            const result = await teamManager.getTeam(9999)
            expect(result).toBeNull()
        })

        it('caches the team for second lookup whether on token or id', async () => {
            const result = await teamManager.getTeam(teamId)
            expect(result?.id).toEqual(teamId)
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)

            const result2 = await teamManager.getTeam(teamId)
            expect(result2?.id).toEqual(teamId)
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)

            const result3 = await teamManager.getTeamByToken(result!.api_token)
            expect(result3?.id).toEqual(teamId)
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)
        })
    })
})
