import { HogFlow } from '~/src/schema/hogflow'
import { Hub } from '~/src/types'
import { closeHub, createHub } from '~/src/utils/db/hub'
import { PostgresUse } from '~/src/utils/db/postgres'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { insertHogFlow } from '../_tests/fixtures-hogflows'
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
        manager = new HogFlowManagerService(hub)

        const team = await getTeam(hub, 2)

        teamId1 = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        hogFlows = []

        hogFlows.push(
            await insertHogFlow(hub.postgres, teamId1, {
                name: 'Test Hog Function team 1',
                status: 'active',
            })
        )

        hogFlows.push(
            await insertHogFlow(hub.postgres, teamId1, {
                name: 'Test Hog Function team 1 - transformation',
                status: 'active',
            })
        )

        hogFlows.push(
            await insertHogFlow(hub.postgres, teamId2, {
                name: 'Test Hog Function team 2',
                status: 'active',
            })
        )

        await manager.start()
    })

    afterEach(async () => {
        await manager.stop()
        await closeHub(hub)
    })

    it('returns the hog flow', async () => {
        let items = await manager.getHogFlowsForTeam(teamId1)

        expect(items).toMatchInlineSnapshot()

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogflow SET name='Test Hog Flow team 1 updated', updated_at = NOW() WHERE id = $1`,
            [hogFlows[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        manager['onHogFlowsReloaded'](teamId1, [hogFlows[0].id])

        items = await manager.getHogFlowsForTeam(teamId1)

        expect(items).toMatchObject([
            {
                id: hogFlows[0].id,
                name: 'Test Hog Flow team 1 updated',
            },
        ])
    })

    // describe('filters hog flow by type', () => {
    //     it('for just transformations', async () => {
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['transformation'])).length).toEqual(1)
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['transformation']))[0].type).toEqual(
    //             'transformation'
    //         )
    //     })

    //     it('for just destinations', async () => {
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['destination'])).length).toEqual(1)
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['destination']))[0].type).toEqual('destination')
    //     })

    //     it('for both', async () => {
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['destination', 'transformation'])).length).toEqual(2)
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['destination', 'transformation']))[0].type).toEqual(
    //             'destination'
    //         )
    //         expect((await manager.getHogFunctionsForTeam(teamId1, ['destination', 'transformation']))[1].type).toEqual(
    //             'transformation'
    //         )
    //     })
    // })

    // describe('getHogFunctionIdsForTeams', () => {
    //     it('returns function IDs filtered by type', async () => {
    //         const result = await manager.getHogFunctionIdsForTeams(
    //             [teamId1, teamId2],
    //             ['destination', 'transformation']
    //         )

    //         expect(result[teamId1]).toHaveLength(2)
    //         expect(result[teamId1]).toContain(hogFunctions[0].id) // destination function
    //         expect(result[teamId1]).toContain(hogFunctions[1].id) // transformation function

    //         expect(result[teamId2]).toHaveLength(1)
    //         expect(result[teamId2]).toContain(hogFunctions[2].id) // destination function
    //     })

    //     it('returns empty arrays for teams with no matching functions', async () => {
    //         const nonExistentTeamId = teamId2 + 1
    //         const result = await manager.getHogFunctionIdsForTeams([nonExistentTeamId], ['transformation'])

    //         expect(result[nonExistentTeamId]).toEqual([])
    //     })

    //     it('filters by specific type correctly', async () => {
    //         const result = await manager.getHogFunctionIdsForTeams([teamId1], ['transformation'])

    //         expect(result[teamId1]).toHaveLength(1)
    //         expect(result[teamId1]).toContain(hogFunctions[1].id) // only the transformation function
    //         expect(result[teamId1]).not.toContain(hogFunctions[0].id) // not the destination function
    //     })

    //     it('handles disabled functions', async () => {
    //         // Disable a function
    //         await hub.db.postgres.query(
    //             PostgresUse.COMMON_WRITE,
    //             `UPDATE posthog_hogfunction SET enabled=false, updated_at = NOW() WHERE id = $1`,
    //             [hogFunctions[0].id],
    //             'testKey'
    //         )

    //         // This is normally dispatched by django
    //         manager['onHogFunctionsReloaded'](teamId1, [hogFunctions[0].id])

    //         const result = await manager.getHogFunctionIdsForTeams([teamId1], ['destination'])
    //         expect(result[teamId1]).toHaveLength(0)
    //     })
    // })

    // it('removes disabled functions', async () => {
    //     let items = await manager.getHogFunctionsForTeam(teamId1, ['destination'])

    //     expect(items).toMatchObject([
    //         {
    //             id: hogFunctions[0].id,
    //         },
    //     ])

    //     await hub.db.postgres.query(
    //         PostgresUse.COMMON_WRITE,
    //         `UPDATE posthog_hogfunction SET enabled=false, updated_at = NOW() WHERE id = $1`,
    //         [hogFunctions[0].id],
    //         'testKey'
    //     )

    //     // This is normally dispatched by django
    //     manager['onHogFunctionsReloaded'](teamId1, [hogFunctions[0].id])

    //     items = await manager.getHogFunctionsForTeam(teamId1, ['destination'])

    //     expect(items).toEqual([])
    // })

    // it('enriches integration inputs if found and belonging to the team', async () => {
    //     const function1Inputs = (await manager.getHogFunctionsForTeam(teamId1, ['destination']))[0].inputs
    //     const function2Inputs = (await manager.getHogFunctionsForTeam(teamId2, ['destination']))[0].inputs

    //     // Only the right team gets the integration inputs enriched
    //     expect(function1Inputs).toEqual({
    //         slack: {
    //             value: {
    //                 team: 'foobar',
    //                 access_token: 'token',
    //                 not_encrypted: 'not-encrypted',
    //                 integrationId: 1,
    //             },
    //         },
    //         normal: {
    //             value: integrations[0].id,
    //         },
    //     })

    //     expect(function2Inputs).toEqual({
    //         slack: {
    //             value: integrations[0].id,
    //         },
    //         normal: {
    //             value: integrations[0].id,
    //         },
    //     })
    // })
})
