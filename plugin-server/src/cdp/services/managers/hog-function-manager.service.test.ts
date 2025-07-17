import { DateTime } from 'luxon'

import { HogFunctionType } from '~/cdp/types'
import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { PostgresUse } from '~/utils/db/postgres'

import { insertHogFunction } from '../../_tests/fixtures'
import { HogFunctionManagerService } from './hog-function-manager.service'

describe('HogFunctionManager', () => {
    jest.setTimeout(2000)
    let hub: Hub
    let manager: HogFunctionManagerService

    let hogFunctions: HogFunctionType[]

    let teamId1: number
    let teamId2: number

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManagerService(hub)

        const team = await getTeam(hub, 2)

        teamId1 = await createTeam(hub.db.postgres, team!.organization_id)
        teamId2 = await createTeam(hub.db.postgres, team!.organization_id)

        hogFunctions = []

        hogFunctions.push(
            await insertHogFunction(hub.postgres, teamId1, {
                name: 'Test Hog Function team 1',
                inputs_schema: [
                    {
                        type: 'string',
                        key: 'input_1',
                    },
                    {
                        type: 'string',
                        key: 'input_2',
                        secret: true,
                    },
                ],
                inputs: {
                    input_1: {
                        value: 'test',
                    },
                },
                encrypted_inputs: hub.encryptedFields.encrypt(JSON.stringify({ input_2: { value: 'test' } })) as any,
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
                        type: 'string',
                        key: 'input_1',
                    },
                ],
                inputs: {
                    input_1: {
                        value: 'test',
                    },
                },
            })
        )
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns the hog functions', async () => {
        let items = await manager.getHogFunctionsForTeam(teamId1, ['destination'])

        expect(items[0].id).toEqual(hogFunctions[0].id)
        expect(items[0].team_id).toEqual(teamId1)

        expect(
            forSnapshot(items, {
                overrides: {
                    created_at: '<REPLACED-DATE>',
                    updated_at: '<REPLACED-DATE>',
                    team_id: '<REPLACED-TEAM-ID>',
                },
            })
        ).toMatchInlineSnapshot(`
            [
              {
                "bytecode": {},
                "created_at": "<REPLACED-DATE>",
                "deleted": false,
                "enabled": true,
                "encrypted_inputs": {
                  "input_2": {
                    "value": "test",
                  },
                },
                "execution_order": null,
                "filters": null,
                "id": "<REPLACED-UUID-0>",
                "inputs": {
                  "input_1": {
                    "value": "test",
                  },
                },
                "inputs_schema": [
                  {
                    "key": "input_1",
                    "type": "string",
                  },
                  {
                    "key": "input_2",
                    "secret": true,
                    "type": "string",
                  },
                ],
                "is_addon_required": true,
                "mappings": null,
                "masking": null,
                "name": "Test Hog Function team 1",
                "team_id": "<REPLACED-TEAM-ID>",
                "template_id": null,
                "type": "destination",
                "updated_at": "<REPLACED-DATE>",
              },
            ]
        `)

        await hub.db.postgres.query(
            PostgresUse.COMMON_WRITE,
            `UPDATE posthog_hogfunction SET name='Test Hog Function team 1 updated', updated_at = NOW() WHERE id = $1`,
            [hogFunctions[0].id],
            'testKey'
        )

        // This is normally dispatched by django
        manager['onHogFunctionsReloaded'](teamId1, [hogFunctions[0].id])

        items = await manager.getHogFunctionsForTeam(teamId1, ['destination'])

        expect(items).toMatchObject([
            {
                id: hogFunctions[0].id,
                name: 'Test Hog Function team 1 updated',
            },
        ])
    })

    describe('filters hog functions by type', () => {
        it('for just transformations', async () => {
            expect((await manager.getHogFunctionsForTeam(teamId1, ['transformation'])).length).toEqual(1)
            expect((await manager.getHogFunctionsForTeam(teamId1, ['transformation']))[0].type).toEqual(
                'transformation'
            )
        })

        it('for just destinations', async () => {
            expect((await manager.getHogFunctionsForTeam(teamId1, ['destination'])).length).toEqual(1)
            expect((await manager.getHogFunctionsForTeam(teamId1, ['destination']))[0].type).toEqual('destination')
        })

        it('for both', async () => {
            expect((await manager.getHogFunctionsForTeam(teamId1, ['destination', 'transformation'])).length).toEqual(2)
            expect((await manager.getHogFunctionsForTeam(teamId1, ['destination', 'transformation']))[0].type).toEqual(
                'destination'
            )
            expect((await manager.getHogFunctionsForTeam(teamId1, ['destination', 'transformation']))[1].type).toEqual(
                'transformation'
            )
        })
    })

    describe('getHogFunctionIdsForTeams', () => {
        it('returns function IDs filtered by type', async () => {
            const result = await manager.getHogFunctionIdsForTeams(
                [teamId1, teamId2],
                ['destination', 'transformation']
            )

            expect(result[teamId1]).toHaveLength(2)
            expect(result[teamId1]).toContain(hogFunctions[0].id) // destination function
            expect(result[teamId1]).toContain(hogFunctions[1].id) // transformation function

            expect(result[teamId2]).toHaveLength(1)
            expect(result[teamId2]).toContain(hogFunctions[2].id) // destination function
        })

        it('returns empty arrays for teams with no matching functions', async () => {
            const nonExistentTeamId = teamId2 + 1
            const result = await manager.getHogFunctionIdsForTeams([nonExistentTeamId], ['transformation'])

            expect(result[nonExistentTeamId]).toEqual([])
        })

        it('filters by specific type correctly', async () => {
            const result = await manager.getHogFunctionIdsForTeams([teamId1], ['transformation'])

            expect(result[teamId1]).toHaveLength(1)
            expect(result[teamId1]).toContain(hogFunctions[1].id) // only the transformation function
            expect(result[teamId1]).not.toContain(hogFunctions[0].id) // not the destination function
        })

        it('handles disabled functions', async () => {
            // Disable a function
            await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_hogfunction SET enabled=false, updated_at = NOW() WHERE id = $1`,
                [hogFunctions[0].id],
                'testKey'
            )

            // This is normally dispatched by django
            manager['onHogFunctionsReloaded'](teamId1, [hogFunctions[0].id])

            const result = await manager.getHogFunctionIdsForTeams([teamId1], ['destination'])
            expect(result[teamId1]).toHaveLength(0)
        })
    })

    it('removes disabled functions', async () => {
        let items = await manager.getHogFunctionsForTeam(teamId1, ['destination'])

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
        manager['onHogFunctionsReloaded'](teamId1, [hogFunctions[0].id])

        items = await manager.getHogFunctionsForTeam(teamId1, ['destination'])

        expect(items).toEqual([])
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

        hub = await createHub()
        await resetTestDatabase()
        manager = new HogFunctionManagerService(hub)

        const team = await getTeam(hub, 2)
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
    })

    afterEach(async () => {
        jest.useRealTimers()
        await closeHub(hub)
    })

    it('maintains correct execution order after individual reloads', async () => {
        // Initial order check
        let teamFunctions = await manager.getHogFunctionsForTeam(teamId, ['transformation'])
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

        manager['onHogFunctionsReloaded'](teamId, [hogFunctions[2].id, hogFunctions[1].id])
        teamFunctions = await manager.getHogFunctionsForTeam(teamId, ['transformation'])
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

        manager['onHogFunctionsReloaded'](teamId, [hogFunctions[2].id, hogFunctions[1].id, hogFunctions[0].id])
        teamFunctions = await manager.getHogFunctionsForTeam(teamId, ['transformation'])
        expect(teamFunctions).toHaveLength(3)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn3', order: 1 },
            { name: 'fn2', order: 2 },
            { name: 'fn1', order: 3 },
        ])
    })

    it('should handle null/undefined execution orders and created_at ordering', async () => {
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn1',
            execution_order: undefined,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 1 }).toISO(),
        })

        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn2',
            execution_order: 1,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 2 }).toISO(),
        })

        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn3',
            execution_order: 1,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 3 }).toISO(),
        })

        manager['onHogFunctionsReloaded'](teamId2, [hogFunctions[2].id, hogFunctions[1].id])
        const teamFunctions = await manager.getHogFunctionsForTeam(teamId2, ['transformation'])

        expect(teamFunctions).toHaveLength(3)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn2', order: 1 }, // First because execution_order=1 and earlier created_at
            { name: 'fn3', order: 1 }, // Second because execution_order=1 but later created_at
            { name: 'fn1', order: null }, // Last because null execution_order
        ])
    })

    it('should maintain order with mixed execution orders and timestamps', async () => {
        // Create functions with different timestamps and execution orders
        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn1',
            execution_order: 2,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 1 }).toISO(),
        })

        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn2',
            execution_order: undefined,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 2 }).toISO(),
        })

        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn3',
            execution_order: 1,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 3 }).toISO(),
        })

        await insertHogFunction(hub.postgres, teamId2, {
            name: 'fn4',
            execution_order: 1,
            type: 'transformation',
            created_at: DateTime.now().plus({ days: 4 }).toISO(),
        })
        manager['onHogFunctionsReloaded'](teamId2, [hogFunctions[2].id, hogFunctions[1].id])
        const teamFunctions = await manager.getHogFunctionsForTeam(teamId2, ['transformation'])

        expect(teamFunctions).toHaveLength(4)
        expect(teamFunctions.map((f) => ({ name: f.name, order: f.execution_order }))).toEqual([
            { name: 'fn3', order: 1 }, // First because execution_order=1 and earlier created_at
            { name: 'fn4', order: 1 }, // Second because execution_order=1 but later created_at
            { name: 'fn1', order: 2 }, // Third because execution_order=2
            { name: 'fn2', order: null }, // Last because null execution_order
        ])
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
