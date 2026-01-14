import { getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { MaterializedColumnSlotManager } from './materialized-column-slot-manager'

describe('MaterializedColumnSlotManager', () => {
    let hub: Hub
    let slotManager: MaterializedColumnSlotManager
    let postgres: PostgresRouter
    let teamId: Team['id']
    let fetchSlotsSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        slotManager = new MaterializedColumnSlotManager(postgres)
        const team = await getFirstTeam(hub)
        teamId = team.id
        fetchSlotsSpy = jest.spyOn(slotManager as any, 'fetchSlots')
    })

    afterEach(async () => {
        await postgres.end()
        await closeHub(hub)
    })

    const createSlot = async (
        teamId: number,
        propertyName: string,
        options: {
            slotIndex?: number
            propertyType?: 'String' | 'Numeric' | 'Boolean' | 'DateTime'
            state?: 'READY' | 'BACKFILL' | 'ERROR'
            materializationType?: 'dmat' | 'eav'
        } = {}
    ) => {
        const { slotIndex = 0, propertyType = 'String', state = 'READY', materializationType = 'eav' } = options

        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_materializedcolumnslot
                (id, team_id, property_name, slot_index, property_type, state, materialization_type, created_at, updated_at)
             VALUES
                (gen_random_uuid(), $1, $2, $3, $4, $5, $6, NOW(), NOW())`,
            [teamId, propertyName, slotIndex, propertyType, state, materializationType],
            'create-test-slot'
        )
    }

    describe('getSlots()', () => {
        it('returns empty array when no slots exist', async () => {
            const result = await slotManager.getSlots(teamId)
            expect(result).toEqual([])
        })

        it('returns slots for the team', async () => {
            await createSlot(teamId, 'browser', { slotIndex: 0, propertyType: 'String' })
            await createSlot(teamId, 'revenue', { slotIndex: 1, propertyType: 'Numeric' })

            const result = await slotManager.getSlots(teamId)

            expect(result).toHaveLength(2)
            expect(result).toEqual([
                {
                    property_name: 'browser',
                    slot_index: 0,
                    property_type: 'String',
                    state: 'READY',
                    materialization_type: 'eav',
                },
                {
                    property_name: 'revenue',
                    slot_index: 1,
                    property_type: 'Numeric',
                    state: 'READY',
                    materialization_type: 'eav',
                },
            ])
        })

        it('returns empty array for non-existent team', async () => {
            const result = await slotManager.getSlots(99999)
            expect(result).toEqual([])
        })

        it('caches slots for second lookup', async () => {
            await createSlot(teamId, 'browser')

            const result1 = await slotManager.getSlots(teamId)
            expect(result1).toHaveLength(1)
            expect(fetchSlotsSpy).toHaveBeenCalledTimes(1)

            const result2 = await slotManager.getSlots(teamId)
            expect(result2).toHaveLength(1)
            expect(fetchSlotsSpy).toHaveBeenCalledTimes(1)
        })

        it('only returns READY and BACKFILL slots, not ERROR', async () => {
            await createSlot(teamId, 'ready_prop', { state: 'READY' })
            await createSlot(teamId, 'backfill_prop', { slotIndex: 1, state: 'BACKFILL' })
            await createSlot(teamId, 'error_prop', { slotIndex: 2, state: 'ERROR' })

            const result = await slotManager.getSlots(teamId)

            expect(result).toHaveLength(2)
            expect(result.map((s) => s.property_name)).toEqual(['ready_prop', 'backfill_prop'])
        })

        it('returns both EAV and DMAT slots', async () => {
            await createSlot(teamId, 'eav_prop', { materializationType: 'eav' })
            await createSlot(teamId, 'dmat_prop', { slotIndex: 1, materializationType: 'dmat' })

            const result = await slotManager.getSlots(teamId)

            expect(result).toHaveLength(2)
            expect(result.map((s) => s.materialization_type)).toEqual(['eav', 'dmat'])
        })
    })

    describe('getSlotsForTeams()', () => {
        it('returns empty object when no teams provided', async () => {
            const result = await slotManager.getSlotsForTeams([])
            expect(result).toEqual({})
        })

        it('returns slots grouped by team', async () => {
            const team2Id = teamId + 1
            // Create team2 in database
            await postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_team (id, uuid, organization_id, project_id, name, created_at, updated_at, anonymize_ips, completed_snippet_onboarding, ingested_event, session_recording_opt_in, api_token, test_account_filters, timezone, app_urls, event_names, event_names_with_usage, event_properties, event_properties_with_usage, event_properties_numerical)
                 SELECT $1, gen_random_uuid(), organization_id, project_id, 'TEST TEAM 2', NOW(), NOW(), false, true, false, true, 'token2', '[]', 'UTC', '{}', '{}', '{}', '{}', '{}', '{}'
                 FROM posthog_team WHERE id = $2`,
                [team2Id, teamId],
                'create-team2'
            )

            await createSlot(teamId, 'prop1')
            await createSlot(team2Id, 'prop2')

            const result = await slotManager.getSlotsForTeams([teamId, team2Id])

            expect(result[String(teamId)]).toHaveLength(1)
            expect(result[String(teamId)][0].property_name).toBe('prop1')
            expect(result[String(team2Id)]).toHaveLength(1)
            expect(result[String(team2Id)][0].property_name).toBe('prop2')
        })

        it('returns empty arrays for teams without slots', async () => {
            const result = await slotManager.getSlotsForTeams([teamId, 99999])

            expect(result[String(teamId)]).toEqual([])
            expect(result['99999']).toEqual([])
        })

        it('efficiently loads multiple teams in single query', async () => {
            await createSlot(teamId, 'prop1')

            const promises = [slotManager.getSlots(teamId), slotManager.getSlots(teamId), slotManager.getSlots(99999)]
            const results = await Promise.all(promises)

            expect(fetchSlotsSpy).toHaveBeenCalledTimes(1)
            expect(results[0]).toHaveLength(1)
            expect(results[1]).toHaveLength(1)
            expect(results[2]).toEqual([])
        })

        it('caches empty results for teams without slots', async () => {
            const result1 = await slotManager.getSlots(99999)
            expect(result1).toEqual([])
            expect(fetchSlotsSpy).toHaveBeenCalledTimes(1)

            const result2 = await slotManager.getSlots(99999)
            expect(result2).toEqual([])
            expect(fetchSlotsSpy).toHaveBeenCalledTimes(1)
        })
    })
})
