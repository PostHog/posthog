import { createTeam, getFirstTeam, resetTestDatabase } from '../../tests/helpers/sql'
import { defaultConfig } from '../config/config'
import { Hub, Team } from '../types'
import { closeHub, createHub } from './db/hub'
import { PostgresRouter, PostgresUse } from './db/postgres'
import { EventSchemaEnforcementManager } from './event-schema-enforcement-manager'

describe('EventSchemaEnforcementManager', () => {
    let hub: Hub
    let schemaManager: EventSchemaEnforcementManager
    let postgres: PostgresRouter
    let teamId: Team['id']
    let projectId: Team['project_id']
    let fetchSchemasSpy: jest.SpyInstance

    beforeEach(async () => {
        const now = Date.now()
        jest.spyOn(Date, 'now').mockImplementation(() => now)

        hub = await createHub()
        await resetTestDatabase()

        postgres = new PostgresRouter(defaultConfig)
        schemaManager = new EventSchemaEnforcementManager(postgres)
        const team = await getFirstTeam(hub)
        teamId = team.id
        projectId = team.project_id
        fetchSchemasSpy = jest.spyOn(schemaManager as any, 'fetchSchemas')
    })

    afterEach(async () => {
        await postgres.end()
        await closeHub(hub)
    })

    /**
     * Creates an event definition.
     * Returns the event_definition_id for further setup.
     */
    const createEventDefinition = async (teamId: number, eventName: string): Promise<string> => {
        const result = await postgres.query<{ id: string }>(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventdefinition
                (id, team_id, name, created_at, last_seen_at)
             VALUES
                (gen_random_uuid(), $1, $2, NOW(), NOW())
             RETURNING id`,
            [teamId, eventName],
            'create-test-event-definition'
        )
        return result.rows[0].id
    }

    /**
     * Creates a property group and returns its ID.
     */
    const createPropertyGroup = async (teamId: number): Promise<string> => {
        const result = await postgres.query<{ id: string }>(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_schemapropertygroup
                (id, team_id, name, created_at)
             VALUES
                (gen_random_uuid(), $1, 'Test Group', NOW())
             RETURNING id`,
            [teamId],
            'create-test-property-group'
        )
        return result.rows[0].id
    }

    /**
     * Creates an event schema linking an event definition to a property group.
     */
    const createEventSchema = async (
        eventDefinitionId: string,
        propertyGroupId: string,
        enforcementMode: 'allow' | 'reject' = 'reject'
    ): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventschema
                (id, event_definition_id, property_group_id, enforcement_mode, created_at)
             VALUES
                (gen_random_uuid(), $1, $2, $3, NOW())`,
            [eventDefinitionId, propertyGroupId, enforcementMode],
            'create-test-event-schema'
        )
    }

    /**
     * Creates a property in a property group.
     */
    const createProperty = async (
        propertyGroupId: string,
        propertyName: string,
        propertyType: string,
        isRequired: boolean
    ): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_schemapropertygroupproperty
                (id, property_group_id, name, property_type, is_required, created_at)
             VALUES
                (gen_random_uuid(), $1, $2, $3, $4, NOW())`,
            [propertyGroupId, propertyName, propertyType, isRequired],
            'create-test-property'
        )
    }

    /**
     * Helper to create a complete enforced schema setup.
     */
    const createEnforcedSchema = async (
        teamId: number,
        eventName: string,
        properties: { name: string; type: string; required: boolean }[]
    ): Promise<void> => {
        const eventDefId = await createEventDefinition(teamId, eventName)
        const propGroupId = await createPropertyGroup(teamId)
        await createEventSchema(eventDefId, propGroupId, 'reject')
        for (const prop of properties) {
            await createProperty(propGroupId, prop.name, prop.type, prop.required)
        }
    }

    describe('getSchemas()', () => {
        it('returns empty array when no schemas exist', async () => {
            const result = await schemaManager.getSchemas(teamId)
            expect(result).toEqual([])
        })

        it('returns empty array when schemas exist but enforcement_mode is allow', async () => {
            const eventDefId = await createEventDefinition(teamId, 'test_event')
            const propGroupId = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroupId, 'allow')
            await createProperty(propGroupId, 'user_id', 'String', true)

            const result = await schemaManager.getSchemas(teamId)
            expect(result).toEqual([])
        })

        it('returns enforced schemas for the team', async () => {
            await createEnforcedSchema(teamId, 'purchase', [
                { name: 'product_id', type: 'String', required: true },
                { name: 'amount', type: 'Numeric', required: true },
            ])

            const result = await schemaManager.getSchemas(teamId)

            expect(result).toHaveLength(1)
            expect(result[0].event_name).toBe('purchase')
            expect(result[0].required_properties).toHaveLength(2)
            expect(result[0].required_properties).toEqual(
                expect.arrayContaining([
                    { name: 'product_id', property_types: ['String'], is_required: true },
                    { name: 'amount', property_types: ['Numeric'], is_required: true },
                ])
            )
        })

        it('only returns required properties, not optional ones', async () => {
            const eventDefId = await createEventDefinition(teamId, 'test_event')
            const propGroupId = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroupId, 'reject')
            await createProperty(propGroupId, 'required_prop', 'String', true)
            await createProperty(propGroupId, 'optional_prop', 'String', false)

            const result = await schemaManager.getSchemas(teamId)

            expect(result).toHaveLength(1)
            expect(result[0].required_properties).toHaveLength(1)
            expect(result[0].required_properties[0].name).toBe('required_prop')
        })

        it('returns empty array for non-existent team', async () => {
            const result = await schemaManager.getSchemas(99999)
            expect(result).toEqual([])
        })

        it('caches schemas for second lookup', async () => {
            await createEnforcedSchema(teamId, 'test_event', [{ name: 'prop', type: 'String', required: true }])

            const result1 = await schemaManager.getSchemas(teamId)
            expect(result1).toHaveLength(1)
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)

            const result2 = await schemaManager.getSchemas(teamId)
            expect(result2).toHaveLength(1)
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)
        })

        it('handles multiple events with enforced schemas', async () => {
            await createEnforcedSchema(teamId, 'event_a', [{ name: 'prop_a', type: 'String', required: true }])
            await createEnforcedSchema(teamId, 'event_b', [{ name: 'prop_b', type: 'Numeric', required: true }])

            const result = await schemaManager.getSchemas(teamId)

            expect(result).toHaveLength(2)
            expect(result.map((s) => s.event_name).sort()).toEqual(['event_a', 'event_b'])
        })

        it('merges property types when property appears in multiple property groups', async () => {
            // Create event with two property groups, each defining the same property with different types
            const eventDefId = await createEventDefinition(teamId, 'test_event')

            const propGroup1 = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroup1, 'reject')
            await createProperty(propGroup1, 'flexible_prop', 'String', true)

            const propGroup2 = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroup2, 'reject')
            await createProperty(propGroup2, 'flexible_prop', 'Numeric', true)

            const result = await schemaManager.getSchemas(teamId)

            expect(result).toHaveLength(1)
            expect(result[0].required_properties).toHaveLength(1)
            expect(result[0].required_properties[0].name).toBe('flexible_prop')
            expect(result[0].required_properties[0].property_types.sort()).toEqual(['Numeric', 'String'])
        })
    })

    describe('getSchemasForTeams()', () => {
        it('returns empty object when no teams provided', async () => {
            const result = await schemaManager.getSchemasForTeams([])
            expect(result).toEqual({})
        })

        it('returns schemas grouped by team', async () => {
            const team2Id = await createTeam(postgres, projectId)

            await createEnforcedSchema(teamId, 'event_1', [{ name: 'prop1', type: 'String', required: true }])
            await createEnforcedSchema(team2Id, 'event_2', [{ name: 'prop2', type: 'Numeric', required: true }])

            const result = await schemaManager.getSchemasForTeams([teamId, team2Id])

            expect(result[String(teamId)]).toHaveLength(1)
            expect(result[String(teamId)][0].event_name).toBe('event_1')
            expect(result[String(team2Id)]).toHaveLength(1)
            expect(result[String(team2Id)][0].event_name).toBe('event_2')
        })

        it('returns empty arrays for teams without enforced schemas', async () => {
            const result = await schemaManager.getSchemasForTeams([teamId, 99999])

            expect(result[String(teamId)]).toEqual([])
            expect(result['99999']).toEqual([])
        })

        it('efficiently loads multiple teams in single query', async () => {
            await createEnforcedSchema(teamId, 'test_event', [{ name: 'prop', type: 'String', required: true }])

            const promises = [
                schemaManager.getSchemas(teamId),
                schemaManager.getSchemas(teamId),
                schemaManager.getSchemas(99999),
            ]
            const results = await Promise.all(promises)

            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)
            expect(results[0]).toHaveLength(1)
            expect(results[1]).toHaveLength(1)
            expect(results[2]).toEqual([])
        })

        it('caches empty results for teams without schemas', async () => {
            const result1 = await schemaManager.getSchemas(99999)
            expect(result1).toEqual([])
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)

            const result2 = await schemaManager.getSchemas(99999)
            expect(result2).toEqual([])
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)
        })
    })
})
