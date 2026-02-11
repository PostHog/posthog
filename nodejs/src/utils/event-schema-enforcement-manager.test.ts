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

    const createEventDefinition = async (
        teamId: number,
        eventName: string,
        enforcementMode: 'allow' | 'reject' = 'allow'
    ): Promise<string> => {
        const result = await postgres.query<{ id: string }>(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventdefinition
                (id, team_id, name, enforcement_mode, created_at, last_seen_at)
             VALUES
                (gen_random_uuid(), $1, $2, $3, NOW(), NOW())
             RETURNING id`,
            [teamId, eventName, enforcementMode],
            'create-test-event-definition'
        )
        return result.rows[0].id
    }

    const createPropertyGroup = async (teamId: number, name?: string): Promise<string> => {
        const groupName = name ?? `Test Group ${Date.now()}-${Math.random().toString(36).slice(2)}`
        const result = await postgres.query<{ id: string }>(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_schemapropertygroup
                (id, team_id, name, description, created_at, updated_at)
             VALUES
                (gen_random_uuid(), $1, $2, '', NOW(), NOW())
             RETURNING id`,
            [teamId, groupName],
            'create-test-property-group'
        )
        return result.rows[0].id
    }

    const createEventSchema = async (eventDefinitionId: string, propertyGroupId: string): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_eventschema
                (id, event_definition_id, property_group_id, created_at, updated_at)
             VALUES
                (gen_random_uuid(), $1, $2, NOW(), NOW())`,
            [eventDefinitionId, propertyGroupId],
            'create-test-event-schema'
        )
    }

    const createProperty = async (
        propertyGroupId: string,
        propertyName: string,
        propertyType: string,
        isRequired: boolean
    ): Promise<void> => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_schemapropertygroupproperty
                (id, property_group_id, name, property_type, is_required, description, created_at, updated_at)
             VALUES
                (gen_random_uuid(), $1, $2, $3, $4, '', NOW(), NOW())`,
            [propertyGroupId, propertyName, propertyType, isRequired],
            'create-test-property'
        )
    }

    const createEnforcedSchema = async (
        teamId: number,
        eventName: string,
        properties: { name: string; type: string; required: boolean }[]
    ): Promise<void> => {
        const eventDefId = await createEventDefinition(teamId, eventName, 'reject')
        const propGroupId = await createPropertyGroup(teamId)
        await createEventSchema(eventDefId, propGroupId)
        for (const prop of properties) {
            await createProperty(propGroupId, prop.name, prop.type, prop.required)
        }
    }

    describe('getSchemas()', () => {
        it('returns empty Map when no schemas exist', async () => {
            const result = await schemaManager.getSchemas(teamId)
            expect(result.size).toBe(0)
        })

        it('returns empty Map when schemas exist but enforcement_mode is allow', async () => {
            const eventDefId = await createEventDefinition(teamId, 'test_event', 'allow')
            const propGroupId = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroupId)
            await createProperty(propGroupId, 'user_id', 'String', true)

            const result = await schemaManager.getSchemas(teamId)
            expect(result.size).toBe(0)
        })

        it('returns enforced schemas for the team', async () => {
            await createEnforcedSchema(teamId, 'purchase', [
                { name: 'product_id', type: 'String', required: true },
                { name: 'amount', type: 'Numeric', required: true },
            ])

            const result = await schemaManager.getSchemas(teamId)

            expect(result.size).toBe(1)
            const schema = result.get('purchase')
            expect(schema).toBeDefined()
            expect(schema!.event_name).toBe('purchase')
            expect(schema!.required_properties.size).toBe(2)
            expect(schema!.required_properties.get('product_id')).toEqual(['String'])
            expect(schema!.required_properties.get('amount')).toEqual(['Numeric'])
        })

        it('only returns required properties, not optional ones', async () => {
            const eventDefId = await createEventDefinition(teamId, 'test_event', 'reject')
            const propGroupId = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroupId)
            await createProperty(propGroupId, 'required_prop', 'String', true)
            await createProperty(propGroupId, 'optional_prop', 'String', false)

            const result = await schemaManager.getSchemas(teamId)

            expect(result.size).toBe(1)
            const schema = result.get('test_event')
            expect(schema!.required_properties.size).toBe(1)
            expect(schema!.required_properties.has('required_prop')).toBe(true)
        })

        it('returns empty Map for non-existent team', async () => {
            const result = await schemaManager.getSchemas(99999)
            expect(result.size).toBe(0)
        })

        it('caches schemas for second lookup', async () => {
            await createEnforcedSchema(teamId, 'test_event', [{ name: 'prop', type: 'String', required: true }])

            const result1 = await schemaManager.getSchemas(teamId)
            expect(result1.size).toBe(1)
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)

            const result2 = await schemaManager.getSchemas(teamId)
            expect(result2.size).toBe(1)
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)
        })

        it('handles multiple events with enforced schemas', async () => {
            await createEnforcedSchema(teamId, 'event_a', [{ name: 'prop_a', type: 'String', required: true }])
            await createEnforcedSchema(teamId, 'event_b', [{ name: 'prop_b', type: 'Numeric', required: true }])

            const result = await schemaManager.getSchemas(teamId)

            expect(result.size).toBe(2)
            expect(Array.from(result.keys()).sort()).toEqual(['event_a', 'event_b'])
        })

        it('collects all types for properties with different types across property groups', async () => {
            const eventDefId = await createEventDefinition(teamId, 'test_event', 'reject')

            const propGroup1 = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroup1)
            await createProperty(propGroup1, 'multi_type_prop', 'String', true)
            await createProperty(propGroup1, 'consistent_prop', 'Numeric', true)

            const propGroup2 = await createPropertyGroup(teamId)
            await createEventSchema(eventDefId, propGroup2)
            await createProperty(propGroup2, 'multi_type_prop', 'Numeric', true)
            await createProperty(propGroup2, 'consistent_prop', 'Numeric', true)

            const result = await schemaManager.getSchemas(teamId)

            expect(result.size).toBe(1)
            const schema = result.get('test_event')
            expect(schema!.required_properties.size).toBe(2)
            expect(schema!.required_properties.get('multi_type_prop')).toEqual(['Numeric', 'String'])
            expect(schema!.required_properties.get('consistent_prop')).toEqual(['Numeric'])
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

            expect(result[String(teamId)].size).toBe(1)
            expect(result[String(teamId)].get('event_1')?.event_name).toBe('event_1')
            expect(result[String(team2Id)].size).toBe(1)
            expect(result[String(team2Id)].get('event_2')?.event_name).toBe('event_2')
        })

        it('returns empty Maps for teams without enforced schemas', async () => {
            const result = await schemaManager.getSchemasForTeams([teamId, 99999])

            expect(result[String(teamId)].size).toBe(0)
            expect(result['99999'].size).toBe(0)
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
            expect(results[0].size).toBe(1)
            expect(results[1].size).toBe(1)
            expect(results[2].size).toBe(0)
        })

        it('caches empty results for teams without schemas', async () => {
            const result1 = await schemaManager.getSchemas(99999)
            expect(result1.size).toBe(0)
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)

            const result2 = await schemaManager.getSchemas(99999)
            expect(result2.size).toBe(0)
            expect(fetchSchemasSpy).toHaveBeenCalledTimes(1)
        })
    })
})
