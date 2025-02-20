import { DateTime, DurationLike } from 'luxon'

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
                            team: 'foobar',
                            access_token: 'token',
                            not_encrypted: 'not-encrypted',
                            integrationId: 1,
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
                    team: 'foobar',
                    access_token: 'token',
                    not_encrypted: 'not-encrypted',
                    integrationId: 1,
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

    let time: DateTime

    const advanceTime = (duration: DurationLike) => {
        time = time.plus(duration)
        jest.setSystemTime(time.toJSDate())
    }

    beforeEach(async () => {
        // Setup fake timers but exclude nextTick and setImmediate
        // faking them can cause tests to hang or timeout
        jest.useFakeTimers({ doNotFake: ['nextTick', 'setImmediate'] })
        time = DateTime.now()
        jest.setSystemTime(time.toJSDate())

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
        advanceTime({ days: 1 })
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn1',
            execution_order: undefined,
            type: 'transformation',
        })

        advanceTime({ days: 1 })
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn2',
            execution_order: 1,
            type: 'transformation',
        })

        advanceTime({ days: 1 })
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
        advanceTime({ days: 1 })
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn1',
            execution_order: 2,
            type: 'transformation',
        })

        advanceTime({ days: 1 })
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn2',
            execution_order: undefined,
            type: 'transformation',
        })

        advanceTime({ days: 1 })
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn3',
            execution_order: 1,
            type: 'transformation',
        })

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

describe('HogFunctionManager - Integration Updates', () => {
    let hub: Hub
    let manager: HogFunctionManagerService
    let teamId: number
    let integration: IntegrationType

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManagerService(hub)

        const team = await hub.db.fetchTeam(2)
        teamId = await createTeam(hub.db.postgres, team!.organization_id)

        // Create an integration
        integration = await insertIntegration(hub.postgres, teamId, {
            kind: 'slack',
            config: { team: 'initial-team' },
            sensitive_config: {
                access_token: hub.encryptedFields.encrypt('initial-token'),
            },
        })

        // Create a hog function that uses this integration
        await insertHogFunction(hub.postgres, teamId, {
            name: 'Test Integration Updates',
            inputs_schema: [
                {
                    type: 'integration',
                    key: 'slack',
                },
            ],
            inputs: {
                slack: {
                    value: integration.id,
                },
            },
        })

        await manager.start(['destination'])
    })

    afterEach(async () => {
        await manager.stop()
        await closeHub(hub)
    })

    it('updates cached integration data when integration changes', async () => {
        // First check - initial state
        const functions = manager.getTeamHogFunctions(teamId)
        expect(functions[0]?.inputs?.slack.value).toEqual({
            team: 'initial-team',
            access_token: 'initial-token',
            integrationId: integration.id,
        })

        // Update the integration in the database
        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_integration 
             SET config = jsonb_set(config, '{team}', '"updated-team"'::jsonb),
                 sensitive_config = jsonb_set(sensitive_config, '{access_token}', $1::jsonb)
             WHERE id = $2`,
            [JSON.stringify(hub.encryptedFields.encrypt('updated-token')), integration.id],
            'updateIntegration'
        )

        await manager.reloadIntegrations(teamId, [integration.id])

        // Verify the database update worked
        const updatedIntegration = await hub.db.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT config, sensitive_config FROM posthog_integration WHERE id = $1`,
            [integration.id],
            'fetchUpdatedIntegration'
        )

        // assert the integration was updated
        expect(updatedIntegration.rows[0].config).toEqual({ team: 'updated-team' })
        expect(hub.encryptedFields.decrypt(updatedIntegration.rows[0].sensitive_config.access_token)).toEqual(
            'updated-token'
        )

        // Trigger integration reload
        await manager.reloadAllIntegrations()
        // Check if the cached data was updated
        const newFunctions = manager.getTeamHogFunctions(teamId)
        expect(newFunctions[0]?.inputs?.slack.value).toEqual({
            team: 'updated-team',
            access_token: 'updated-token',
            integrationId: integration.id,
        })
    })
})

describe('sanitize', () => {
    let hub: Hub
    let manager: HogFunctionManagerService

    beforeEach(async () => {
        hub = await createHub()
        manager = new HogFunctionManagerService(hub)
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('should handle encrypted_inputs as an object', () => {
        const item: HogFunctionType = {
            id: '1',
            team_id: 1,
            name: 'test',
            type: 'destination',
            enabled: true,
            deleted: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            encrypted_inputs: {
                apiKey: {
                    value: 'test-key',
                    order: 0,
                    bytecode: ['_H', 1, 32, 'test-key'],
                },
            },
        } as unknown as HogFunctionType

        manager.sanitize([item])

        // Should preserve the original object
        expect(item.encrypted_inputs).toEqual({
            apiKey: {
                value: 'test-key',
                order: 0,
                bytecode: ['_H', 1, 32, 'test-key'],
            },
        })
    })

    it('should handle encrypted_inputs as a string', () => {
        const encryptedString = hub.encryptedFields.encrypt(
            JSON.stringify({
                apiKey: {
                    value: 'test-key',
                    order: 0,
                },
            })
        )

        const item: HogFunctionType = {
            id: '1',
            team_id: 1,
            name: 'test',
            type: 'destination',
            enabled: true,
            deleted: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            encrypted_inputs: encryptedString,
        } as unknown as HogFunctionType

        manager.sanitize([item])

        // Should decrypt and parse the string
        expect(item.encrypted_inputs).toEqual({
            apiKey: {
                value: 'test-key',
                order: 0,
            },
        })
    })

    it('should capture exception for invalid encrypted string while preserving value', () => {
        const item: HogFunctionType = {
            id: '1',
            team_id: 1,
            name: 'test',
            type: 'destination',
            enabled: true,
            deleted: false,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            encrypted_inputs: 'invalid-encrypted-string',
        } as unknown as HogFunctionType

        manager.sanitize([item])

        // Should preserve the original invalid string
        expect(item.encrypted_inputs).toBe('invalid-encrypted-string')
    })

    it('should not capture exception for undefined values', () => {
        const items: HogFunctionType[] = [
            {
                id: '1',
                team_id: 1,
                name: 'test-undefined',
                type: 'destination',
                enabled: true,
                deleted: false,
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
                encrypted_inputs: undefined,
            } as unknown as HogFunctionType,
        ]

        manager.sanitize(items)

        // Should preserve undefined value
        expect(items[0].encrypted_inputs).toBeUndefined()
    })
})
