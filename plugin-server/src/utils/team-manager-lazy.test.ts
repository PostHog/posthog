import { forSnapshot } from '~/tests/helpers/snapshots'

import { createOrganization, createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { TeamManagerLazy } from './team-manager-lazy'

describe('TeamManager()', () => {
    let hub: Hub
    let teamManager: TeamManagerLazy
    let postgres: PostgresRouter
    let teamId: Team['id']
    let team2Id: Team['id']
    let team3Id: Team['id']
    let teamToken: Team['api_token']
    let otherOrganizationId: string
    let organizationId: Team['organization_id']
    let fetchTeamsSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        teamManager = new TeamManagerLazy(postgres)
        const team = await getFirstTeam(hub)
        teamId = team.id
        teamToken = team.api_token
        organizationId = team.organization_id
        otherOrganizationId = await createOrganization(postgres)
        team2Id = await createTeam(postgres, team.organization_id)
        team3Id = await createTeam(postgres, otherOrganizationId)
        fetchTeamsSpy = jest.spyOn(teamManager as any, 'fetchTeams')
    })

    const updateOrganizationAvailableFeatures = async (
        organizationId: string,
        features: { key: string; name: string }[]
    ) => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_organization SET available_product_features = $1 WHERE id = $2`,
            [features, organizationId],
            'change-team-available-features'
        )
    }

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

        it('efficiently loads multiple teams', async () => {
            const promises = [
                teamManager.getTeam(teamId),
                teamManager.getTeamByToken(teamToken),
                teamManager.getTeam(teamId),
                teamManager.getTeamByToken(teamToken),
                teamManager.getTeamByToken('missing'),
            ]
            const results = await Promise.all(promises)
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)
            expect(results.map((r) => r?.id)).toEqual([teamId, teamId, teamId, teamId, undefined])
        })
    })

    describe('hasAvailableFeature()', () => {
        it('returns false by default', async () => {
            const result = await teamManager.hasAvailableFeature(teamId, 'feature1')
            expect(result).toBe(false)
        })

        it('returns false if the available features does not exist', async () => {
            await updateOrganizationAvailableFeatures(organizationId, [{ key: 'feature1', name: 'Feature 1' }])
            const result = await teamManager.hasAvailableFeature(teamId, 'feature2')
            expect(result).toBe(false)
        })

        it('returns true if the available features exists', async () => {
            await updateOrganizationAvailableFeatures(organizationId, [{ key: 'feature1', name: 'Feature 1' }])
            const result = await teamManager.hasAvailableFeature(teamId, 'feature1')
            expect(result).toBe(true)
        })

        it('refreshes relevant teams when the organization available features change', async () => {
            await updateOrganizationAvailableFeatures(organizationId, [{ key: 'feature1', name: 'Feature 1' }])
            const results = await Promise.all([
                teamManager.hasAvailableFeature(teamId, 'feature1'),
                teamManager.hasAvailableFeature(team2Id, 'feature1'),
                teamManager.hasAvailableFeature(team3Id, 'feature1'),
            ])
            expect(results).toEqual([true, true, false])

            await updateOrganizationAvailableFeatures(organizationId, [{ key: 'feature2', name: 'Feature 2' }])
            teamManager.orgAvailableFeaturesChanged(organizationId)
            const results2 = await Promise.all([
                teamManager.hasAvailableFeature(teamId, 'feature1'),
                teamManager.hasAvailableFeature(team2Id, 'feature1'),
                teamManager.hasAvailableFeature(team3Id, 'feature1'),
            ])
            expect(results2).toEqual([false, false, false])
        })
    })
})
