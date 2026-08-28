import { randomUUID } from 'crypto'

import { forSnapshot } from '~/tests/helpers/snapshots'
import {
    createTeam,
    createTestTeamFixture,
    getTeam,
    insertRow,
    updateOrganizationAvailableFeatures,
} from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { defaultConfig } from '../config/config'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { captureTeamEvent } from './posthog'
import { TeamManager } from './team-manager'

jest.mock('~/common/utils/posthog', () => ({
    captureTeamEvent: jest.fn(),
}))

const mockCaptureTeamEvent = captureTeamEvent as jest.Mock

describe('TeamManager()', () => {
    let hub: Hub
    let teamManager: TeamManager
    let postgres: PostgresRouter
    let teamId: Team['id']
    let teamToken: Team['api_token']
    let organizationId: Team['organization_id']
    let fetchTeamsSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()

        postgres = new PostgresRouter(defaultConfig)
        teamManager = new TeamManager(postgres)
        const fixture = await createTestTeamFixture(hub.postgres, { cookieless_server_hash_mode: 2 })
        const fixtureOrganizationId = fixture.organizationId
        await updateOrganizationAvailableFeatures(hub.postgres, fixtureOrganizationId, [
            { key: 'data_pipelines', name: 'Data Pipelines' },
        ])
        const team = (await getTeam(hub.postgres, fixture.team.id))!
        teamId = team.id
        teamToken = team.api_token
        organizationId = team.organization_id
        fetchTeamsSpy = jest.spyOn(teamManager as any, 'fetchTeams')
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    describe('getTeam()', () => {
        it('returns the team', async () => {
            const result = await teamManager.getTeam(teamId)
            // This one test is a snapshot to ensure the team object is stable
            expect(
                forSnapshot(result, {
                    overrides: { api_token: '<TEAM_API_TOKEN>', id: '<TEAM_ID>', project_id: '<PROJECT_ID>' },
                })
            ).toMatchInlineSnapshot(`
                {
                  "anonymize_ips": false,
                  "api_token": "<TEAM_API_TOKEN>",
                  "available_features": [
                    "data_pipelines",
                  ],
                  "cookieless_server_hash_mode": 2,
                  "drop_events_older_than_seconds": null,
                  "extra_settings": null,
                  "heatmaps_opt_in": null,
                  "id": "<TEAM_ID>",
                  "ingested_event": true,
                  "logs_settings": null,
                  "minimal_flag_called_events": false,
                  "name": "TEST PROJECT",
                  "organization_id": "<REPLACED-UUID-1>",
                  "person_display_name_properties": [],
                  "person_processing_opt_out": null,
                  "project_id": "<PROJECT_ID>",
                  "secret_api_token": null,
                  "session_recording_opt_in": true,
                  "timezone": "UTC",
                  "uuid": "<REPLACED-UUID-0>",
                }
                `)
        })

        it('returns null if the team does not exist', async () => {
            const result = await teamManager.getTeam(9999)
            expect(result).toBeNull()
        })

        it('returns null if the team ID is larger than 32-bit integer and could overflow DB col type', async () => {
            const result = await teamManager.getTeam(12345678901234)
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

        it('caches null results for non-existing tokens', async () => {
            const nonExistentToken = 'non-existent-token'
            const result1 = await teamManager.getTeamByToken(nonExistentToken)
            expect(result1).toBeNull()
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)

            const result2 = await teamManager.getTeamByToken(nonExistentToken)
            expect(result2).toBeNull()
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)
        })

        it('correctly handles mix of existing and non-existing teams', async () => {
            const nonExistentId = 9999
            const [existingTeam, nonExistingTeam] = await Promise.all([
                teamManager.getTeam(teamId),
                teamManager.getTeam(nonExistentId),
            ])

            expect(existingTeam?.id).toEqual(teamId)
            expect(nonExistingTeam).toBeNull()
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)

            // Second fetch should use cache for both
            const [existingTeam2, nonExistingTeam2] = await Promise.all([
                teamManager.getTeam(teamId),
                teamManager.getTeam(nonExistentId),
            ])
            expect(existingTeam2?.id).toEqual(teamId)
            expect(nonExistingTeam2).toBeNull()
            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)
        })

        it('correctly fetches drop_events_older_than setting', async () => {
            // Get the organization ID from the first team
            const firstTeam = await teamManager.getTeam(teamId)
            const organizationId = firstTeam!.organization_id

            // Create a new team with drop_events_older_than set
            const newTeamId = await createTeam(postgres, organizationId, undefined, {
                drop_events_older_than: 86400, // 24 hours in seconds
            })

            // Fetch the new team
            const newTeam = await teamManager.getTeam(newTeamId)
            expect(newTeam).not.toBeNull()
            expect(newTeam!.drop_events_older_than_seconds).toBe(86400)

            // Verify the setting is also accessible via token
            const newTeamByToken = await teamManager.getTeamByToken(newTeam!.api_token)
            expect(newTeamByToken).not.toBeNull()
            expect(newTeamByToken!.drop_events_older_than_seconds).toBe(86400)
        })

        it('correctly fetches drop_events_older_than setting when set to 0', async () => {
            // Get the organization ID from the first team
            const firstTeam = await teamManager.getTeam(teamId)
            const organizationId = firstTeam!.organization_id

            // Create a new team with drop_events_older_than set to 0
            const newTeamId = await createTeam(postgres, organizationId, undefined, {
                drop_events_older_than: 0, // 0 seconds
            })

            // Fetch the new team
            const newTeam = await teamManager.getTeam(newTeamId)
            expect(newTeam).not.toBeNull()
            expect(newTeam!.drop_events_older_than_seconds).toBe(0)

            // Verify the setting is also accessible via token
            const newTeamByToken = await teamManager.getTeamByToken(newTeam!.api_token)
            expect(newTeamByToken).not.toBeNull()
            expect(newTeamByToken!.drop_events_older_than_seconds).toBe(0)
        })

        it('correctly fetches drop_events_older_than setting when set to null', async () => {
            // Get the organization ID from the first team
            const firstTeam = await teamManager.getTeam(teamId)
            const organizationId = firstTeam!.organization_id

            // Create a new team with drop_events_older_than set to null
            const newTeamId = await createTeam(postgres, organizationId, undefined, {
                drop_events_older_than: null,
            })

            // Fetch the new team
            const newTeam = await teamManager.getTeam(newTeamId)
            expect(newTeam).not.toBeNull()
            expect(newTeam!.drop_events_older_than_seconds).toBeNull()

            // Verify the setting is also accessible via token
            const newTeamByToken = await teamManager.getTeamByToken(newTeam!.api_token)
            expect(newTeamByToken).not.toBeNull()
            expect(newTeamByToken!.drop_events_older_than_seconds).toBeNull()
        })

        it('defaults minimal_flag_called_events to false when no TeamFeatureFlagsConfig row exists', async () => {
            const newTeamId = await createTeam(postgres, organizationId)

            const newTeam = await teamManager.getTeam(newTeamId)
            expect(newTeam).not.toBeNull()
            expect(newTeam!.minimal_flag_called_events).toBe(false)
        })

        it('reflects minimal_flag_called_events when a TeamFeatureFlagsConfig row exists', async () => {
            const newTeamId = await createTeam(postgres, organizationId)
            await insertRow(postgres, 'feature_flags_teamfeatureflagsconfig', {
                team_id: newTeamId,
                minimal_flag_called_events: true,
            })

            const newTeam = await teamManager.getTeam(newTeamId)
            expect(newTeam).not.toBeNull()
            expect(newTeam!.minimal_flag_called_events).toBe(true)
        })

        it('does not leak minimal_flag_called_events across teams', async () => {
            const teamA = await createTeam(postgres, organizationId)
            const teamB = await createTeam(postgres, organizationId)
            await insertRow(postgres, 'feature_flags_teamfeatureflagsconfig', {
                team_id: teamA,
                minimal_flag_called_events: true,
            })

            expect((await teamManager.getTeam(teamA))!.minimal_flag_called_events).toBe(true)
            expect((await teamManager.getTeam(teamB))!.minimal_flag_called_events).toBe(false)
        })
    })

    describe('hasAvailableFeature()', () => {
        it('returns false by default', async () => {
            await updateOrganizationAvailableFeatures(postgres, organizationId, [])
            const result = await teamManager.hasAvailableFeature(teamId, 'data_pipelines')
            expect(result).toBe(false)
        })

        it('returns false if the available features does not exist', async () => {
            await updateOrganizationAvailableFeatures(postgres, organizationId, [
                { key: 'not_data_pipelines', name: 'Feature 1' },
            ])
            const result = await teamManager.hasAvailableFeature(teamId, 'data_pipelines')
            expect(result).toBe(false)
        })

        it('returns true if the available features exists', async () => {
            await updateOrganizationAvailableFeatures(postgres, organizationId, [
                { key: 'data_pipelines', name: 'Feature 1' },
            ])
            const result = await teamManager.hasAvailableFeature(teamId, 'data_pipelines')
            expect(result).toBe(true)
        })
    })

    describe('setTeamIngestedEvent()', () => {
        let newTeamToken: string
        let newTeam: Team

        const readIngestedEvent = async (id: Team['id']): Promise<boolean> => {
            const result = await postgres.query<{ ingested_event: boolean }>(
                PostgresUse.COMMON_READ,
                'SELECT ingested_event FROM posthog_team WHERE id = $1',
                [id],
                'test-read-ingested-event'
            )
            return result.rows[0].ingested_event
        }

        beforeEach(async () => {
            newTeamToken = randomUUID()
            await createTeam(postgres, organizationId, newTeamToken, { ingested_event: false })
            const loaded = await teamManager.getTeamByToken(newTeamToken)
            expect(loaded?.ingested_event).toBe(false)
            newTeam = loaded as Team
        })

        it('flips the flag and captures the first event for each org member', async () => {
            await teamManager.setTeamIngestedEvent(newTeam, { $lib: 'web' })

            expect(await readIngestedEvent(newTeam.id)).toBe(true)
            expect(mockCaptureTeamEvent).toHaveBeenCalledTimes(1)
            expect(mockCaptureTeamEvent).toHaveBeenCalledWith(
                newTeam,
                'first team event ingested',
                expect.objectContaining({ sdk: 'web' }),
                expect.any(String)
            )
        })

        it('does nothing on a repeat call through a stale team object', async () => {
            await teamManager.setTeamIngestedEvent(newTeam, { $lib: 'web' })
            mockCaptureTeamEvent.mockClear()

            // `newTeam` still reads ingested_event=false, which is the stale-cache case exactly.
            await teamManager.setTeamIngestedEvent(newTeam, { $lib: 'web' })

            expect(mockCaptureTeamEvent).not.toHaveBeenCalled()
            expect(await readIngestedEvent(newTeam.id)).toBe(true)
        })

        it('captures exactly once when two workers race on the same new team', async () => {
            await Promise.all([
                teamManager.setTeamIngestedEvent(newTeam, { $lib: 'web' }),
                teamManager.setTeamIngestedEvent({ ...newTeam }, { $lib: 'web' }),
            ])

            expect(mockCaptureTeamEvent).toHaveBeenCalledTimes(1)
            expect(await readIngestedEvent(newTeam.id)).toBe(true)
        })

        it('refreshes the token cache entry so the next lookup sees the flag', async () => {
            await teamManager.setTeamIngestedEvent(newTeam, { $lib: 'web' })
            fetchTeamsSpy.mockClear()

            // Ingestion only ever looks teams up by token, so the token entry is the one that has
            // to be invalidated. `Date.now` is frozen here, so nothing else can expire it.
            const reloaded = await teamManager.getTeamByToken(newTeamToken)

            expect(fetchTeamsSpy).toHaveBeenCalledTimes(1)
            expect(reloaded?.ingested_event).toBe(true)
        })

        it('issues no query at all for a team already flagged as ingested', async () => {
            const querySpy = jest.spyOn(postgres, 'query')

            await teamManager.setTeamIngestedEvent({ ...newTeam, ingested_event: true }, { $lib: 'web' })

            expect(querySpy).not.toHaveBeenCalled()
            expect(mockCaptureTeamEvent).not.toHaveBeenCalled()
        })
    })
})
