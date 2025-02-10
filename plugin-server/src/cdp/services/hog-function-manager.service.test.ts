import { HogFunctionType, IntegrationType } from '~/src/cdp/types'
import { Hub } from '~/src/types'
import { closeHub, createHub } from '~/src/utils/db/hub'
import { PostgresUse } from '~/src/utils/db/postgres'
import { insertHogFunction, insertIntegration } from '~/tests/cdp/fixtures'
import { createTeam, resetTestDatabase } from '~/tests/helpers/sql'

import { HogFunctionManagerService } from './hog-function-manager.service'

describe('HogFunctionManager', () => {
    let hub: Hub
    let manager: HogFunctionManagerService

    let hogFunctions: HogFunctionType[]
    let integrations: IntegrationType[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManagerService(hub)

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
                name: 'Test Hog Function team 1 - transformation',
                type: 'transformation',
                inputs_schema: [],
                inputs: {},
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
    })

    afterEach(async () => {
        await manager.stop()
        await closeHub(hub)
    })

    it('returns the hog functions', async () => {
        await manager.start(['destination'])
        let items = manager.getTeamHogFunctions(teamId1)

        expect(items).toEqual([
            expect.objectContaining({
                id: hogFunctions[0].id,
                team_id: teamId1,
                name: 'Test Hog Function team 1',
                type: 'destination',
                enabled: true,
                execution_order: null,
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
                mappings: null,
                template_id: null,
                depends_on_integration_ids: new Set([integrations[0].id]),
            }),
        ])

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET name='Test Hog Function team 1 updated', updated_at = NOW() WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadAllHogFunctions()

        items = manager.getTeamHogFunctions(teamId1)

        expect(items).toMatchObject([
            {
                id: hogFunctions[0].id,
                name: 'Test Hog Function team 1 updated',
            },
        ])
    })

    describe('filters hog functions by type', () => {
        it('for just transformations', async () => {
            await manager.start(['transformation'])
            expect(manager.getTeamHogFunctions(teamId1).length).toEqual(1)
            expect(manager.getTeamHogFunctions(teamId1)[0].type).toEqual('transformation')
        })

        it('for just destinations', async () => {
            await manager.start(['destination'])
            expect(manager.getTeamHogFunctions(teamId1).length).toEqual(1)
            expect(manager.getTeamHogFunctions(teamId1)[0].type).toEqual('destination')
        })

        it('for both', async () => {
            await manager.start(['destination', 'transformation'])
            expect(manager.getTeamHogFunctions(teamId1).length).toEqual(2)
            expect(manager.getTeamHogFunctions(teamId1)[0].type).toEqual('destination')
            expect(manager.getTeamHogFunctions(teamId1)[1].type).toEqual('transformation')
        })
    })

    it('removes disabled functions', async () => {
        await manager.start(['destination'])
        let items = manager.getTeamHogFunctions(teamId1)

        expect(items).toMatchObject([
            {
                id: hogFunctions[0].id,
            },
        ])

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET enabled=false, updated_at = NOW() WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        await manager.reloadAllHogFunctions()

        items = manager.getTeamHogFunctions(teamId1)

        expect(items).toEqual([])
    })

    it('enriches integration inputs if found and belonging to the team', async () => {
        await manager.start(['destination'])
        const function1Inputs = manager.getTeamHogFunctions(teamId1)[0].inputs
        const function2Inputs = manager.getTeamHogFunctions(teamId2)[0].inputs

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

describe('Hogfunction Manager - Execution Order', () => {
    let hub: Hub
    let manager: HogFunctionManagerService
    let hogFunctions: HogFunctionType[]
    let teamId: number
    let teamId2: number
    beforeEach(async () => {
        // Setup fake timers but exclude nextTick and setImmediate
        // faking them can cause tests to hang or timeout
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate'] })

        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManagerService(hub)

        const team = await hub.db.fetchTeam(2)
        teamId = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        hogFunctions = []

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId, {
                name: 'fn1',
                execution_order: 1,
                type: 'transformation',
            })
        )

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId, {
                name: 'fn2',
                execution_order: 2,
                type: 'transformation',
            })
        )

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId, {
                name: 'fn3',
                execution_order: 3,
                type: 'transformation',
            })
        )

        await manager.start(['transformation'])
    })

    afterEach(async () => {
        jest.useRealTimers()
        await manager.stop()
        await closeHub(hub)
    })

    it('maintains correct execution order after individual reloads', async () => {
        // Initial order check
        let teamFunctions = manager.getTeamHogFunctions(teamId)
        expect(teamFunctions).toHaveLength(3)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn1', order: 1 },
            { name: 'fn2', order: 2 },
            { name: 'fn3', order: 3 },
        ])

        // change order in database and reload single functions to simulate changes over the django API.

        // Update fn2's to be last
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET execution_order = 3, updated_at = NOW() WHERE id = $1`,
            [hogFunctions[1].id],
            'testKey'
        )

        // therefore fn3's execution order should be 2
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET execution_order = 2, updated_at = NOW() WHERE id = $1`,
            [hogFunctions[2].id],
            'testKey'
        )

        await manager.reloadAllHogFunctions()
        teamFunctions = manager.getTeamHogFunctions(teamId)
        expect(teamFunctions).toHaveLength(3)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn1', order: 1 },
            { name: 'fn3', order: 2 },
            { name: 'fn2', order: 3 },
        ])

        // change fn1 to be last
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET execution_order = 3, updated_at = NOW() WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )
        // change fn3 to be first
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET execution_order = 1, updated_at = NOW() WHERE id = $1`,
            [hogFunctions[2].id],
            'testKey'
        )
        // change fn2 to be second
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET execution_order = 2, updated_at = NOW() WHERE id = $1`,
            [hogFunctions[1].id],
            'testKey'
        )

        await manager.reloadAllHogFunctions()
        teamFunctions = manager.getTeamHogFunctions(teamId)
        expect(teamFunctions).toHaveLength(3)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn3', order: 1 },
            { name: 'fn2', order: 2 },
            { name: 'fn1', order: 3 },
        ])
    })

    it('should handle null/undefined execution orders and created_at ordering', async () => {
        // Set initial time
        jest.setSystemTime(new Date('2024-01-01T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn1',
            execution_order: null,
            type: 'transformation',
        })

        // Advance time by 1 day
        jest.setSystemTime(new Date('2024-01-02T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn2',
            execution_order: 1,
            type: 'transformation',
        })

        // Advance time by another day
        jest.setSystemTime(new Date('2024-01-03T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn3',
            execution_order: 1,
            type: 'transformation',
        })

        await manager.reloadAllHogFunctions()
        const teamFunctions = manager.getTeamHogFunctions(teamId2)

        expect(teamFunctions).toHaveLength(3)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn2', order: 1 }, // First because execution_order=1 and earlier created_at
            { name: 'fn3', order: 1 }, // Second because execution_order=1 but later created_at
            { name: 'fn1', order: null }, // Last because null execution_order
        ])
    })

    it('should maintain order with mixed execution orders and timestamps', async () => {
        // Create functions with different timestamps and execution orders
        jest.setSystemTime(new Date('2024-01-01T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn1',
            execution_order: 2,
            type: 'transformation',
        })

        jest.setSystemTime(new Date('2024-01-02T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn2',
            execution_order: null,
            type: 'transformation',
        })

        jest.setSystemTime(new Date('2024-01-03T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn3',
            execution_order: 1,
            type: 'transformation',
        })

        jest.setSystemTime(new Date('2024-01-04T00:00:00Z'))
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn4',
            execution_order: 1,
            type: 'transformation',
        })

        await manager.reloadAllHogFunctions()
        const teamFunctions = manager.getTeamHogFunctions(teamId2)

        expect(teamFunctions).toHaveLength(4)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn3', order: 1 }, // First because execution_order=1 and earlier created_at
            { name: 'fn4', order: 1 }, // Second because execution_order=1 but later created_at
            { name: 'fn1', order: 2 }, // Third because execution_order=2
            { name: 'fn2', order: null }, // Last because null execution_order
        ])
    })
})
