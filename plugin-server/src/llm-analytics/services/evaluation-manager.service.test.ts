import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { insertEvaluation } from '../_tests/fixtures'
import { Evaluation } from '../types'
import { EvaluationManagerService } from './evaluation-manager.service'

describe('EvaluationManagerService', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: EvaluationManagerService

    let evaluations: Evaluation[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new EvaluationManagerService(hub)

        const team = await getTeam(hub, 2)

        teamId1 = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        evaluations = []

        evaluations.push(
            await insertEvaluation(hub.postgres, teamId1, {
                name: 'Test Evaluation team 1',
                evaluation_type: 'llm_judge',
                evaluation_config: { prompt: 'Test prompt 1' },
                output_type: 'boolean',
                output_config: {},
                enabled: true,
            })
        )

        evaluations.push(
            await insertEvaluation(hub.postgres, teamId1, {
                name: 'Test Evaluation team 1 - disabled',
                evaluation_type: 'llm_judge',
                evaluation_config: { prompt: 'Test prompt disabled' },
                output_type: 'boolean',
                output_config: {},
                enabled: false,
            })
        )

        evaluations.push(
            await insertEvaluation(hub.postgres, teamId2, {
                name: 'Test Evaluation team 2',
                evaluation_type: 'llm_judge',
                evaluation_config: { prompt: 'Test prompt 2' },
                output_type: 'boolean',
                output_config: {},
                enabled: true,
            })
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns evaluations for a team', async () => {
        const items = await manager.getEvaluationsForTeam(teamId1)

        expect(items).toHaveLength(1)
        expect(items[0].id).toEqual(evaluations[0].id)
        expect(items[0].team_id).toEqual(teamId1)
        expect(items[0].name).toEqual('Test Evaluation team 1')
    })

    it('returns evaluations for multiple teams in batch', async () => {
        const result = await manager.getEvaluationsForTeams([teamId1, teamId2])

        expect(result[teamId1]).toHaveLength(1)
        expect(result[teamId2]).toHaveLength(1)
        expect(result[teamId1][0].id).toEqual(evaluations[0].id)
        expect(result[teamId2][0].id).toEqual(evaluations[2].id)
    })

    it('returns empty array for teams with no evaluations', async () => {
        const nonExistentTeamId = teamId2 + 1
        const items = await manager.getEvaluationsForTeam(nonExistentTeamId)

        expect(items).toEqual([])
    })

    it('filters out disabled evaluations', async () => {
        const items = await manager.getEvaluationsForTeam(teamId1)

        expect(items).toHaveLength(1)
        expect(items[0].id).toEqual(evaluations[0].id)
    })

    it('filters out deleted evaluations', async () => {
        // Mark first evaluation as deleted
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_evaluation SET deleted=true, updated_at = NOW() WHERE id = $1`,
            [evaluations[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        manager['onEvaluationsReloaded'](teamId1, [evaluations[0].id])

        const items = await manager.getEvaluationsForTeam(teamId1)

        expect(items).toHaveLength(0)
    })

    it('caches evaluations and uses cache on subsequent calls', async () => {
        // First call
        const items1 = await manager.getEvaluationsForTeam(teamId1)
        expect(items1).toHaveLength(1)

        // Update the database without triggering reload
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_evaluation SET name='Updated Name', updated_at = NOW() WHERE id = $1`,
            [evaluations[0].id],
            'testKey'
        )

        // Second call should still return cached data
        const items2 = await manager.getEvaluationsForTeam(teamId1)
        expect(items2).toHaveLength(1)
        expect(items2[0].name).toEqual('Test Evaluation team 1') // Not updated yet
    })

    it('reloads evaluations when pubsub message received', async () => {
        const itemsBefore = await manager.getEvaluationsForTeam(teamId1)
        expect(itemsBefore).toHaveLength(1)

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_evaluation SET name='Updated Evaluation', updated_at = NOW() WHERE id = $1`,
            [evaluations[0].id],
            'testKey'
        )

        manager['onEvaluationsReloaded'](teamId1, [evaluations[0].id])

        const itemsAfter = await manager.getEvaluationsForTeam(teamId1)

        expect(itemsAfter).toMatchObject([
            {
                id: evaluations[0].id,
                name: 'Updated Evaluation',
            },
        ])
    })

    it('filters out evaluation when disabled via reload', async () => {
        const itemsBefore = await manager.getEvaluationsForTeam(teamId1)
        expect(itemsBefore).toHaveLength(1)

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE llm_analytics_evaluation SET enabled=false, updated_at = NOW() WHERE id = $1`,
            [evaluations[0].id],
            'testKey'
        )

        manager['onEvaluationsReloaded'](teamId1, [evaluations[0].id])

        const itemsAfter = await manager.getEvaluationsForTeam(teamId1)
        expect(itemsAfter).toHaveLength(0)
    })

    it('handles non-existent team IDs gracefully in batch fetch', async () => {
        const nonExistentTeamId = teamId2 + 100
        const result = await manager.getEvaluationsForTeams([teamId1, nonExistentTeamId, teamId2])

        expect(result[teamId1]).toHaveLength(1)
        expect(result[nonExistentTeamId]).toEqual([])
        expect(result[teamId2]).toHaveLength(1)
    })

    it('handles evaluations with bytecode errors', async () => {
        await insertEvaluation(hub.postgres, teamId1, {
            name: 'Evaluation with bytecode error',
            evaluation_type: 'llm_judge',
            evaluation_config: { prompt: 'Test prompt' },
            output_type: 'boolean',
            output_config: {},
            enabled: true,
            conditions: [
                {
                    id: 'cond-1',
                    rollout_percentage: 100,
                    properties: [],
                    bytecode_error: 'Failed to compile',
                },
            ],
        })

        const items = await manager.getEvaluationsForTeam(teamId1)

        expect(items).toHaveLength(2)
        const evalWithError = items.find((item) => item.name === 'Evaluation with bytecode error')
        expect(evalWithError).toBeDefined()
        expect(evalWithError!.conditions[0].bytecode_error).toEqual('Failed to compile')
    })
})
