import { Pool } from 'pg'

import { defaultConfig } from '../../src/config/config'
import { Hub, PropertyOperator, RawAction, Team } from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { DependencyUnavailableError, RedisOperationError } from '../../src/utils/db/error'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../src/utils/db/postgres'
import { UUIDT } from '../../src/utils/utils'
import { getFirstTeam, insertRow, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/logger')

describe('DB', () => {
    let hub: Hub
    let db: DB

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        db = hub.db

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await db.redisPool.release(redis)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    function runPGQuery(queryString: string) {
        return db.postgres.query(PostgresUse.COMMON_WRITE, queryString, [], 'testQuery')
    }

    describe('fetchAllActionsGroupedByTeam() and fetchAction()', () => {
        const insertAction = async (action: Partial<RawAction> = {}) => {
            await insertRow(hub.db.postgres, 'posthog_action', {
                id: 69,
                team_id: 2,
                name: 'Test Action',
                description: '',
                created_at: new Date().toISOString(),
                created_by_id: 1001,
                deleted: false,
                post_to_slack: true,
                slack_message_format: '',
                is_calculating: false,
                updated_at: new Date().toISOString(),
                last_calculated_at: new Date().toISOString(),
                ...action,
            })
        }

        beforeEach(async () => {
            await insertAction()
        })

        it('returns actions with `post_to_slack', async () => {
            const result = await db.fetchAllActionsGroupedByTeam()

            expect(result).toMatchObject({
                2: {
                    69: {
                        id: 69,
                        team_id: 2,
                        name: 'Test Action',
                        deleted: false,
                        post_to_slack: true,
                        slack_message_format: '',
                        is_calculating: false,
                        steps: [],
                        hooks: [],
                    },
                },
            })
        })

        it('returns actions with steps', async () => {
            await insertAction({
                id: 70,
                steps_json: [
                    {
                        tag_name: null,
                        text: null,
                        text_matching: null,
                        href: null,
                        href_matching: null,
                        selector: null,
                        url: null,
                        url_matching: null,
                        event: null,
                        properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                    },
                ],
            })

            const result = await db.fetchAllActionsGroupedByTeam()

            expect(result[2][70]).toMatchObject({
                id: 70,
                team_id: 2,
                name: 'Test Action',
                deleted: false,
                post_to_slack: true,
                slack_message_format: '',
                is_calculating: false,
                steps: [
                    {
                        tag_name: null,
                        text: null,
                        text_matching: null,
                        href: null,
                        href_matching: null,
                        selector: null,
                        url: null,
                        url_matching: null,
                        event: null,
                        properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                    },
                ],
                hooks: [],
            })

            const action = await db.fetchAction(70)
            expect(action!.steps).toEqual([
                {
                    tag_name: null,
                    text: null,
                    text_matching: null,
                    href: null,
                    href_matching: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ])
        })

        it('returns actions with correct `ee_hook`', async () => {
            await runPGQuery('UPDATE posthog_action SET post_to_slack = false')
            await insertRow(hub.db.postgres, 'ee_hook', {
                id: 'abc',
                team_id: 2,
                user_id: 1001,
                resource_id: 69,
                event: 'action_performed',
                target: 'https://example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            })
            const result = await db.fetchAllActionsGroupedByTeam()

            expect(result).toMatchObject({
                2: {
                    69: {
                        id: 69,
                        team_id: 2,
                        name: 'Test Action',
                        deleted: false,
                        post_to_slack: false,
                        slack_message_format: '',
                        is_calculating: false,
                        steps: [],
                        hooks: [
                            {
                                id: 'abc',
                                team_id: 2,
                                resource_id: 69,
                                event: 'action_performed',
                                target: 'https://example.com/',
                            },
                        ],
                    },
                },
            })

            expect(await db.fetchAction(69)).toEqual({
                ...result[2][69],
                steps_json: null, // Temporary diff whilst we migrate to this new field
            })
        })

        it('does not return actions that dont match conditions', async () => {
            await runPGQuery('UPDATE posthog_action SET post_to_slack = false')

            const result = await db.fetchAllActionsGroupedByTeam()
            expect(result).toEqual({})

            expect(await db.fetchAction(69)).toEqual(null)
        })

        it('does not return actions which are deleted', async () => {
            await runPGQuery('UPDATE posthog_action SET deleted = true')

            const result = await db.fetchAllActionsGroupedByTeam()
            expect(result).toEqual({})

            expect(await db.fetchAction(69)).toEqual(null)
        })

        it('does not return actions with incorrect ee_hook', async () => {
            await runPGQuery('UPDATE posthog_action SET post_to_slack = false')
            await insertRow(hub.db.postgres, 'ee_hook', {
                id: 'abc',
                team_id: 2,
                user_id: 1001,
                resource_id: 69,
                event: 'event_performed',
                target: 'https://example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            })
            await insertRow(hub.db.postgres, 'ee_hook', {
                id: 'efg',
                team_id: 2,
                user_id: 1001,
                resource_id: 70,
                event: 'event_performed',
                target: 'https://example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            })

            const result = await db.fetchAllActionsGroupedByTeam()
            expect(result).toEqual({})

            expect(await db.fetchAction(69)).toEqual(null)
        })

        describe('FOSS', () => {
            beforeEach(async () => {
                await runPGQuery('ALTER TABLE ee_hook RENAME TO ee_hook_backup')
            })

            afterEach(async () => {
                await runPGQuery('ALTER TABLE ee_hook_backup RENAME TO ee_hook')
            })

            it('does not blow up', async () => {
                await runPGQuery('UPDATE posthog_action SET post_to_slack = false')

                const result = await db.fetchAllActionsGroupedByTeam()
                expect(result).toEqual({})
                expect(await db.fetchAction(69)).toEqual(null)
            })
        })
    })

    describe('getPluginSource', () => {
        let team: Team
        let plugin: number

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            const plug = await db.postgres.query(
                PostgresUse.COMMON_WRITE,
                'INSERT INTO posthog_plugin (name, organization_id, config_schema, from_json, from_web, is_global, is_preinstalled, is_stateless, created_at, capabilities) values($1, $2, $3, false, false, false, false, false, $4, $5) RETURNING id',
                ['My Plug', team.organization_id, [], new Date(), {}],
                ''
            )
            plugin = plug.rows[0].id
        })

        test('fetches from the database', async () => {
            let source = await db.getPluginSource(plugin, 'index.ts')
            expect(source).toBe(null)

            await db.postgres.query(
                PostgresUse.COMMON_WRITE,
                'INSERT INTO posthog_pluginsourcefile (id, plugin_id, filename, source) values($1, $2, $3, $4)',
                [new UUIDT().toString(), plugin, 'index.ts', 'USE THE SOURCE'],
                ''
            )

            source = await db.getPluginSource(plugin, 'index.ts')
            expect(source).toBe('USE THE SOURCE')
        })
    })

    describe('redis', () => {
        describe('instrumentRedisQuery', () => {
            const otherErrorType = new Error('other error type')

            it('should only throw Redis errors for operations', async () => {
                hub.redisPool.acquire = jest.fn().mockImplementation(() => ({
                    get: jest.fn().mockImplementation(() => {
                        throw otherErrorType
                    }),
                }))
                hub.redisPool.release = jest.fn()
                await expect(hub.db.redisGet('testKey', 'testDefaultValue', 'testTag')).rejects.toBeInstanceOf(
                    RedisOperationError
                )
            })
            it('should only throw Redis errors for pool acquire', async () => {
                hub.redisPool.acquire = jest.fn().mockImplementation(() => {
                    throw otherErrorType
                })
                hub.redisPool.release = jest.fn()
                await expect(hub.db.redisGet('testKey', 'testDefaultValue', 'testTag')).rejects.toBeInstanceOf(
                    RedisOperationError
                )
            })

            it('should only throw Redis errors for pool release', async () => {
                hub.redisPool.acquire = jest.fn().mockImplementation(() => ({
                    get: jest.fn().mockImplementation(() => {
                        return 'testValue'
                    }),
                }))
                hub.redisPool.release = jest.fn().mockImplementation(() => {
                    throw otherErrorType
                })
                await expect(hub.db.redisGet('testKey', 'testDefaultValue', 'testTag')).rejects.toBeInstanceOf(
                    RedisOperationError
                )
            })
        })

        describe('get', () => {
            const defaultValue = 'testDefaultValue'
            const value = 'testValue'
            const key = 'testKey'
            const tag = 'testTag'
            it('should get a value that was previously set', async () => {
                await hub.db.redisSet(key, value, tag)
                const result = await hub.db.redisGet(key, defaultValue, tag)
                expect(result).toEqual(value)
            })
            it('should return the default value if there is no value already set', async () => {
                const result = await hub.db.redisGet(key, defaultValue, tag)
                expect(result).toEqual(defaultValue)
            })
        })

        describe('buffer operations', () => {
            it('writes and reads buffers', async () => {
                const buffer = Buffer.from('test')
                await db.redisSetBuffer('test', buffer, 'testTag', 60)
                const result = await db.redisGetBuffer('test', 'testTag')
                expect(result).toEqual(buffer)
            })
        })

        describe('redisSetNX', () => {
            it('it should only set a value if there is not already one present', async () => {
                const set1 = await db.redisSetNX('test', 'first', 'testTag')
                expect(set1).toEqual('OK')
                const get1 = await db.redisGet('test', '', 'testTag')
                expect(get1).toEqual('first')

                const set2 = await db.redisSetNX('test', 'second', 'testTag')
                expect(set2).toEqual(null)
                const get2 = await db.redisGet('test', '', 'testTag')
                expect(get2).toEqual('first')
            })

            it('it should only set a value if there is not already one present, with a ttl', async () => {
                const set1 = await db.redisSetNX('test', 'first', 'testTag', 60)
                expect(set1).toEqual('OK')
                const get1 = await db.redisGet('test', '', 'testTag')
                expect(get1).toEqual('first')

                const set2 = await db.redisSetNX('test', 'second', 'testTag', 60)
                expect(set2).toEqual(null)
                const get2 = await db.redisGet('test', '', 'testTag')
                expect(get2).toEqual('first')
            })
        })

        describe('redisSAddAndSCard', () => {
            it('it should add a value to a set and return the number of elements in the set', async () => {
                const add1 = await db.redisSAddAndSCard('test', 'A')
                expect(add1).toEqual(1)
                const add2 = await db.redisSAddAndSCard('test', 'A')
                expect(add2).toEqual(1)
                const add3 = await db.redisSAddAndSCard('test', 'B')
                expect(add3).toEqual(2)
                const add4 = await db.redisSAddAndSCard('test', 'B')
                expect(add4).toEqual(2)
                const add5 = await db.redisSAddAndSCard('test', 'A')
                expect(add5).toEqual(2)
            })

            it('it should add a value to a set and return the number of elements in the set, with a TTL', async () => {
                const add1 = await db.redisSAddAndSCard('test', 'A', 60)
                expect(add1).toEqual(1)
                const add2 = await db.redisSAddAndSCard('test', 'A', 60)
                expect(add2).toEqual(1)
                const add3 = await db.redisSAddAndSCard('test', 'B', 60)
                expect(add3).toEqual(2)
                const add4 = await db.redisSAddAndSCard('test', 'B', 60)
                expect(add4).toEqual(2)
                const add5 = await db.redisSAddAndSCard('test', 'A', 60)
                expect(add5).toEqual(2)
            })
        })

        describe('redisSCard', () => {
            it('it should return the number of elements in the set', async () => {
                await db.redisSAddAndSCard('test', 'A')
                const scard1 = await db.redisSCard('test')
                expect(scard1).toEqual(1)

                await db.redisSAddAndSCard('test', 'B')
                const scard2 = await db.redisSCard('test')
                expect(scard2).toEqual(2)

                await db.redisSAddAndSCard('test', 'B')
                const scard3 = await db.redisSCard('test')
                expect(scard3).toEqual(2)
            })
        })
    })
})

describe('PostgresRouter()', () => {
    test('throws DependencyUnavailableError on postgres errors', async () => {
        const errorMessage =
            'connection to server at "posthog-pgbouncer" (171.20.65.128), port 6543 failed: server closed the connection unexpectedly'
        const pgQueryMock = jest.spyOn(Pool.prototype, 'query').mockImplementation(() => {
            return Promise.reject(new Error(errorMessage))
        })

        const router = new PostgresRouter(defaultConfig)
        await expect(router.query(PostgresUse.COMMON_WRITE, 'SELECT 1;', [], 'testing')).rejects.toEqual(
            new DependencyUnavailableError(errorMessage, 'Postgres', new Error(errorMessage))
        )
        pgQueryMock.mockRestore()
    })
})
