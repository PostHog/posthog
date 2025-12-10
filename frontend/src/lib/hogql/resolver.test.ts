/**
 * HogQL Resolver Tests
 *
 * Tests for type resolution in HogQL queries
 * Based on posthog/hogql/test/test_resolver.py
 */

import { Database, resolveTypes, type HogQLContext } from './resolver'
import { getDatabaseSchema } from './autocomplete'
import { parseHogQLSelect } from './parser'
import type * as ast from './ast'

describe('HogQL Resolver', () => {
    let database: Database
    let context: HogQLContext

    beforeAll(async () => {
        const schema = await getDatabaseSchema()
        database = new Database(schema)
        context = {
            database,
            teamId: 1,
            enableSelectQueries: true,
        }
    })

    describe('Basic Resolution', () => {
        it('should resolve simple SELECT query', async () => {
            const query = 'SELECT event FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            // Check that types were assigned
            expect(resolved.type).toBeDefined()
            // Check it's a SelectQueryType by checking for its properties
            expect(resolved.type).toHaveProperty('tables')
            expect(resolved.type).toHaveProperty('columns')

            // Check that the field was resolved
            expect(resolved.select[0].type).toBeDefined()
        })

        it('should resolve fields with table alias', async () => {
            const query = 'SELECT e.event FROM events e'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            expect(resolved.type).toBeDefined()
            expect(resolved.select[0].type).toBeDefined()
        })

        it('should resolve WHERE clause', async () => {
            const query = "SELECT event FROM events WHERE event = 'test'"
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            expect(resolved.where).toBeDefined()
            expect(resolved.where?.type).toBeDefined()
            // Check it's a BooleanType by checking for data_type property
            expect((resolved.where?.type as any)?.data_type).toBe('bool')
        })

        it('should resolve constants', async () => {
            const query = "SELECT 1, 'hello', true, 1.5"
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            // Check that all constants have types
            expect(resolved.select.length).toBe(4)
            resolved.select.forEach((expr) => {
                expect(expr.type).toBeDefined()
            })
        })

        it('should throw on double resolution', async () => {
            const query = 'SELECT event FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse')

            // Try to resolve again - should throw
            expect(() => {
                resolveTypes(resolved, context, 'clickhouse')
            }).toThrow(/Type already resolved/)
        })

        it('should throw on unknown field in clickhouse dialect', async () => {
            const query = 'SELECT unknown_field FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            expect(() => {
                resolveTypes(parsed, context, 'clickhouse')
            }).toThrow(/Unable to resolve field/)
        })

        it('should not throw on unknown field in hogql dialect', async () => {
            const query = 'SELECT unknown_field FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'hogql') as ast.SelectQuery

            // Should have a FieldAliasType (fields are wrapped in aliases)
            expect(resolved.select[0].type).toBeTruthy()
            // Check it's a FieldAliasType by checking for alias property
            expect((resolved.select[0].type as any)?.alias).toBeTruthy()
        })
    })

    describe('Nested Fields', () => {
        it('should resolve nested table fields', async () => {
            const query = 'SELECT pdi.distinct_id FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            expect(resolved.select[0].type).toBeDefined()
        })
    })

    describe('Subqueries', () => {
        it('should resolve subquery in FROM clause', async () => {
            const query = 'SELECT b FROM (SELECT event as b FROM events)'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            expect(resolved.type).toBeDefined()
            expect(resolved.select[0].type).toBeDefined()
        })
    })

    describe('Aliases', () => {
        it('should resolve column aliases', async () => {
            const query = 'SELECT event as e FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            const resolved = resolveTypes(parsed, context, 'clickhouse') as ast.SelectQuery

            const aliasNode = resolved.select[0] as ast.Alias
            expect(aliasNode.type).toBeTruthy()
            // Check it's a FieldAliasType by checking its properties
            expect((aliasNode.type as any)?.alias).toBe('e')
            expect((aliasNode.type as any)?.type).toBeTruthy()
        })

        it('should throw on duplicate aliases', async () => {
            const query = 'SELECT event as x, timestamp as x FROM events'
            const parsed = await parseHogQLSelect(query)

            if ('message' in parsed) {
                throw new Error(`Parse error: ${parsed.message}`)
            }

            expect(() => {
                resolveTypes(parsed, context, 'clickhouse')
            }).toThrow(/Cannot redefine an alias/)
        })
    })
})
