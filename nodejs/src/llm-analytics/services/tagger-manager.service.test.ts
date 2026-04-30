import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { insertTagger } from '../_tests/fixtures'
import { Tagger } from '../types'
import { TaggerManagerService } from './tagger-manager.service'

describe('TaggerManagerService', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: TaggerManagerService

    let taggers: Tagger[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new TaggerManagerService(hub.postgres, hub.pubSub)

        const team = await getTeam(hub.postgres, 2)

        teamId1 = await createTeam(hub.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.postgres, team!.organization_id)

        taggers = []

        taggers.push(
            await insertTagger(hub.postgres, teamId1, {
                name: 'Test Tagger team 1',
                enabled: true,
            })
        )

        taggers.push(
            await insertTagger(hub.postgres, teamId1, {
                name: 'Test Tagger team 1 - disabled',
                enabled: false,
            })
        )

        taggers.push(
            await insertTagger(hub.postgres, teamId2, {
                name: 'Test Tagger team 2',
                enabled: true,
            })
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns taggers for a team', async () => {
        const items = await manager.getTaggersForTeam(teamId1)

        expect(items).toHaveLength(1)
        expect(items[0].id).toEqual(taggers[0].id)
        expect(items[0].team_id).toEqual(teamId1)
        expect(items[0].name).toEqual('Test Tagger team 1')
    })

    it('returns taggers for multiple teams in batch', async () => {
        const result = await manager.getTaggersForTeams([teamId1, teamId2])

        expect(result[teamId1]).toHaveLength(1)
        expect(result[teamId2]).toHaveLength(1)
        expect(result[teamId1][0].id).toEqual(taggers[0].id)
        expect(result[teamId2][0].id).toEqual(taggers[2].id)
    })

    it('returns empty array for teams with no taggers', async () => {
        const nonExistentTeamId = teamId2 + 1
        const items = await manager.getTaggersForTeam(nonExistentTeamId)

        expect(items).toEqual([])
    })

    it('filters out disabled taggers', async () => {
        const items = await manager.getTaggersForTeam(teamId1)

        expect(items).toHaveLength(1)
        expect(items[0].id).toEqual(taggers[0].id)
    })

    it('filters out deleted taggers (detail-fetch guard)', async () => {
        // Soft-delete the first tagger
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_tagger SET deleted = true, updated_at = NOW() WHERE id = $1`,
            [taggers[0].id],
            'testKey'
        )

        // Force the manager to refetch (would normally be triggered by the post_save signal)
        manager['onTaggersReloaded'](teamId1, [taggers[0].id])

        const items = await manager.getTaggersForTeam(teamId1)
        expect(items).toHaveLength(0)
    })

    it('caches taggers and uses cache on subsequent calls', async () => {
        const items1 = await manager.getTaggersForTeam(teamId1)
        expect(items1).toHaveLength(1)

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_tagger SET name = 'Updated Name', updated_at = NOW() WHERE id = $1`,
            [taggers[0].id],
            'testKey'
        )

        const items2 = await manager.getTaggersForTeam(teamId1)
        expect(items2).toHaveLength(1)
        expect(items2[0].name).toEqual('Test Tagger team 1') // cached, not the updated value
    })

    it('reloads taggers when pubsub message received', async () => {
        const itemsBefore = await manager.getTaggersForTeam(teamId1)
        expect(itemsBefore).toHaveLength(1)

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_tagger SET name = 'Updated Tagger', updated_at = NOW() WHERE id = $1`,
            [taggers[0].id],
            'testKey'
        )

        manager['onTaggersReloaded'](teamId1, [taggers[0].id])

        const itemsAfter = await manager.getTaggersForTeam(teamId1)
        expect(itemsAfter).toMatchObject([
            {
                id: taggers[0].id,
                name: 'Updated Tagger',
            },
        ])
    })

    it('filters out tagger when disabled via reload (auto-disable path)', async () => {
        const itemsBefore = await manager.getTaggersForTeam(teamId1)
        expect(itemsBefore).toHaveLength(1)

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_tagger SET enabled = false, updated_at = NOW() WHERE id = $1`,
            [taggers[0].id],
            'testKey'
        )

        manager['onTaggersReloaded'](teamId1, [taggers[0].id])

        const itemsAfter = await manager.getTaggersForTeam(teamId1)
        expect(itemsAfter).toHaveLength(0)
    })

    it('handles non-existent team IDs gracefully in batch fetch', async () => {
        const nonExistentTeamId = teamId2 + 100
        const result = await manager.getTaggersForTeams([teamId1, nonExistentTeamId, teamId2])

        expect(result[teamId1]).toHaveLength(1)
        expect(result[nonExistentTeamId]).toEqual([])
        expect(result[teamId2]).toHaveLength(1)
    })

    it('exposes single-tagger getter that returns null for unknown ids', async () => {
        const known = await manager.getTagger(taggers[0].id)
        expect(known?.id).toEqual(taggers[0].id)

        const unknown = await manager.getTagger('00000000-0000-0000-0000-000000000000')
        expect(unknown).toBeNull()
    })
})
