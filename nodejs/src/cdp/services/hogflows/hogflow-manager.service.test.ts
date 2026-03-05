import '~/tests/helpers/mocks/date.mock'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlow } from '~/schema/hogflow'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { insertHogFlow } from '../../_tests/fixtures-hogflows'
import { HogFlowManagerService } from './hogflow-manager.service'

describe('HogFlowManager', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: HogFlowManagerService

    let hogFlows: HogFlow[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFlowManagerService(hub.postgres, hub.pubSub, hub.encryptedFields)

        const team = await getTeam(hub, 2)

        teamId1 = await createTeam(hub.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.postgres, team!.organization_id)

        hogFlows = []

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 1')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .build()
            )
        )

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 1 - other')
                    .withTeamId(teamId1)
                    .withStatus('active')
                    .build()
            )
        )

        hogFlows.push(
            await insertHogFlow(
                hub.postgres,
                new FixtureHogFlowBuilder()
                    .withName('Test Hog Flow team 2')
                    .withTeamId(teamId2)
                    .withStatus('active')
                    .build()
            )
        )
    })

    const setEncryptedInputs = async (
        flowId: string,
        encryptedInputs: Record<string, Record<string, any>>
    ): Promise<void> => {
        const encryptedValue = hub.encryptedFields.encrypt(JSON.stringify(encryptedInputs))
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogflow SET encrypted_inputs = $1 WHERE id = $2`,
            [encryptedValue, flowId],
            'setEncryptedInputs'
        )
    }

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns the hog flow', async () => {
        let items = await manager.getHogFlowsForTeam(teamId1)
        expect(items.map((item) => item.team_id)).toEqual([teamId1, teamId1])

        expect(
            forSnapshot(items, {
                overrides: {
                    team_id: 'TEAM_ID',
                    created_at: 'CREATED_AT',
                    updated_at: 'UPDATED_AT',
                },
            })
        ).toMatchSnapshot()

        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogflow SET name='Test Hog Flow team 1 updated', updated_at = NOW() WHERE id = $1`,
            [hogFlows[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])

        items = await manager.getHogFlowsForTeam(teamId1)

        expect(items.find((item) => item.id === hogFlows[0].id)).toMatchObject({
            id: hogFlows[0].id,
            name: 'Test Hog Flow team 1 updated',
        })
    })

    describe('encrypted_inputs', () => {
        it('decrypts encrypted_inputs when fetching a hog flow', async () => {
            const encryptedInputs = {
                action_1: { api_key: { value: 'sk-secret-123' } },
            }
            await setEncryptedInputs(hogFlows[0].id, encryptedInputs)

            manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])
            const flow = await manager.getHogFlow(hogFlows[0].id)

            expect(flow!.encrypted_inputs).toEqual(encryptedInputs)
        })

        it('returns null encrypted_inputs when none are set', async () => {
            const flow = await manager.getHogFlow(hogFlows[0].id)
            expect(flow!.encrypted_inputs).toBeFalsy()
        })

        it('decrypts encrypted_inputs with multiple action IDs', async () => {
            const encryptedInputs = {
                action_1: { api_key: { value: 'sk-first' } },
                action_2: { token: { value: 'tok-second' } },
            }
            await setEncryptedInputs(hogFlows[0].id, encryptedInputs)

            manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])
            const flow = await manager.getHogFlow(hogFlows[0].id)

            expect(flow!.encrypted_inputs).toEqual(encryptedInputs)
        })
    })

    describe('getHogFlowIdsForTeam', () => {
        it('returns function IDs', async () => {
            const result = await manager.getHogFlowIdsForTeams([teamId1, teamId2])

            expect(result[teamId1]).toHaveLength(2)
            expect(result[teamId1]).toContain(hogFlows[0].id)
            expect(result[teamId1]).toContain(hogFlows[1].id)

            expect(result[teamId2]).toHaveLength(1)
            expect(result[teamId2]).toContain(hogFlows[2].id)
        })

        it('returns empty arrays for teams with no matching functions', async () => {
            const nonExistentTeamId = teamId2 + 1
            const result = await manager.getHogFlowIdsForTeams([nonExistentTeamId])
            expect(result[nonExistentTeamId]).toEqual([])
        })

        it('handles archived hog flows', async () => {
            const originalResult = await manager.getHogFlowIdsForTeams([teamId1, teamId2])
            expect(originalResult[teamId1]).toHaveLength(2)

            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogflow SET status='archived', updated_at = NOW() WHERE id = $1`,
                [hogFlows[0].id],
                'testKey'
            )

            manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])

            const result = await manager.getHogFlowIdsForTeams([teamId1])
            expect(result[teamId1]).toHaveLength(1)
            expect(result[teamId1]).not.toContain(hogFlows[0].id)
        })
    })
})
