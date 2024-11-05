import { HogFunctionManager } from '../../src/cdp/hog-function-manager'
import { HogFunctionType, IntegrationType } from '../../src/cdp/types'
import { Hub } from '../../src/types'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresUse } from '../../src/utils/db/postgres'
import { createTeam, resetTestDatabase } from '../helpers/sql'
import { insertHogFunction, insertIntegration } from './fixtures'

describe('HogFunctionManager', () => {
    let hub: Hub
    let manager: HogFunctionManager

    let hogFunctions: HogFunctionType[]
    let integrations: IntegrationType[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManager(hub)

        const team = await hub.db.fetchTeam(2)

        teamId1 = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        hogFunctions = []
        integrations = []

        integrations.push(
            await insertIntegration(hub.postgres, teamId1, {
                kind: 'slack',
                config: { team: 'foobar' },
                sensitive_config: {
                    access_token: hub.encryptedFields.encrypt('token'),
                    not_encrypted: 'not-encrypted',
                },
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
            await insertHogFunction(hub.postgres, teamId1, {
                name: 'Email Provider team 1',
                type: 'email',
                inputs_schema: [
                    {
                        type: 'email',
                        key: 'message',
                    },
                ],
                inputs: {
                    email: {
                        value: { from: 'me@a.com', to: 'you@b.com', subject: 'subject', html: 'text' },
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
        await manager.stop()
        await closeHub(hub)
    })

    it('returns the hog functions', async () => {
        let items = manager.getTeamHogDestinations(teamId1)

        expect(items).toEqual([
            {
                id: hogFunctions[0].id,
                team_id: teamId1,
                name: 'Test Hog Function team 1',
                type: 'destination',
                enabled: true,
                bytecode: {},
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
                            not_encrypted: 'not-encrypted',
                        },
                    },
                    normal: {
                        value: integrations[0].id,
                    },
                },
                encrypted_inputs: null,
                masking: null,
                depends_on_integration_ids: new Set([integrations[0].id]),
            },
        ])

        const allFunctions = manager.getTeamHogFunctions(teamId1)
        expect(allFunctions.length).toEqual(2)
        expect(allFunctions.map((f) => f.type).sort()).toEqual(['destination', 'email'])

        const emailProvider = manager.getTeamHogEmailProvider(teamId1)
        expect(emailProvider.type).toEqual('email')

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET name='Test Hog Function team 1 updated' WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadHogFunctions(teamId1, [hogFunctions[0].id])

        items = manager.getTeamHogDestinations(teamId1)

        expect(items).toMatchObject([
            {
                id: hogFunctions[0].id,
                name: 'Test Hog Function team 1 updated',
            },
        ])
    })

    it('removes disabled functions', async () => {
        let items = manager.getTeamHogDestinations(teamId1)

        expect(items).toMatchObject([
            {
                id: hogFunctions[0].id,
            },
        ])

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET enabled=false WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadHogFunctions(teamId1, [hogFunctions[0].id])

        items = manager.getTeamHogDestinations(teamId1)

        expect(items).toEqual([])
    })

    it('enriches integration inputs if found and belonging to the team', () => {
        const function1Inputs = manager.getTeamHogDestinations(teamId1)[0].inputs
        const function2Inputs = manager.getTeamHogDestinations(teamId2)[0].inputs

        // Only the right team gets the integration inputs enriched
        expect(function1Inputs).toEqual({
            slack: {
                value: {
                    access_token: 'token',
                    team: 'foobar',
                    not_encrypted: 'not-encrypted',
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
