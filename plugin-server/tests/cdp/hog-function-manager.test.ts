import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { HogFunctionType, IntegrationType } from '../../src/cdp/types'
import { Hub } from '../../src/types'
import { createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { createTeam, resetTestDatabase } from '../helpers/sql'
import { insertHogFunction, insertIntegration } from './fixtures'

describe('HogFunctionManager', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let manager: HogFunctionManager

    let hogFunctions: HogFunctionType[]
    let integrations: IntegrationType[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManager(hub.postgres, hub)

        const team = await hub.db.fetchTeam(2)

        teamId1 = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        hogFunctions = []
        integrations = []

        integrations.push(
            await insertIntegration(hub.postgres, teamId1, {
                kind: 'slack',
                config: { team: 'foobar' },
                sensitive_config: { access_token: 'token' },
            })
        )

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId1, {
                name: 'Test Hog Function team 1',
                inputs_schema: [
                    {
                        type: 'integration',
                        key: 'slack',
                    },
                ],
                inputs: {
                    slack: {
                        value: integrations[0].id,
                    },
                    normal: {
                        value: integrations[0].id,
                    },
                },
            })
        )

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId2, {
                name: 'Test Hog Function team 2',
                inputs_schema: [
                    {
                        type: 'integration',
                        key: 'slack',
                    },
                ],
                inputs: {
                    slack: {
                        value: integrations[0].id,
                    },
                    normal: {
                        value: integrations[0].id,
                    },
                },
            })
        )

        await manager.start()
    })

    afterEach(async () => {
        await closeServer()
    })

    it('returns the hog functions', async () => {
        let functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap).toEqual({
            [hogFunctions[0].id]: {
                id: hogFunctions[0].id,
                team_id: teamId1,
                name: 'Test Hog Function team 1',
                enabled: true,
                bytecode: null,
                filters: null,
                inputs_schema: [
                    {
                        key: 'slack',
                        type: 'integration',
                    },
                ],
                inputs: {
                    slack: {
                        value: {
                            access_token: 'token',
                            team: 'foobar',
                        },
                    },
                    normal: {
                        value: integrations[0].id,
                    },
                },
            },
        })

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET name='Test Hog Function team 1 updated' WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadHogFunctions(teamId1, [hogFunctions[0].id])

        functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap[hogFunctions[0].id]).toMatchObject({
            id: hogFunctions[0].id,
            name: 'Test Hog Function team 1 updated',
        })
    })

    it('removes disabled functions', async () => {
        let functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap).toHaveProperty(hogFunctions[0].id)

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET enabled=false WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadHogFunctions(teamId1, [hogFunctions[0].id])

        functionsMap = manager.getTeamHogFunctions(teamId1)

        expect(functionsMap).not.toHaveProperty(hogFunctions[0].id)
    })

    it('enriches integration inputs if found and belonging to the team', () => {
        const function1Inputs = manager.getTeamHogFunctions(teamId1)[hogFunctions[0].id].inputs
        const function2Inputs = manager.getTeamHogFunctions(teamId2)[hogFunctions[1].id].inputs

        // Only the right team gets the integration inputs enriched
        expect(function1Inputs).toEqual({
            slack: {
                value: {
                    access_token: 'token',
                    team: 'foobar',
                },
            },
            normal: {
                value: integrations[0].id,
            },
        })

        expect(function2Inputs).toEqual({
            slack: {
                value: integrations[0].id,
            },
            normal: {
                value: integrations[0].id,
            },
        })
    })
})
