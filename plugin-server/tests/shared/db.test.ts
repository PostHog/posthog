import { DateTime } from 'luxon'

import { Hub, Person, PropertyOperator, PropertyUpdateOperation, Team } from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { createHub } from '../../src/utils/db/hub'
import { RaceConditionError, UUIDT } from '../../src/utils/utils'
import { getFirstTeam, insertRow, resetTestDatabase } from '../helpers/sql'
import { plugin60 } from './../helpers/plugins'

jest.mock('../../src/utils/status')

describe('DB', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        db = hub.db
    })

    afterEach(async () => {
        await closeServer()
    })

    const TEAM_ID = 2
    const ACTION_ID = 69
    const ACTION_STEP_ID = 913
    const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()

    test('fetchAllActionsGroupedByTeam', async () => {
        const action = await db.fetchAllActionsGroupedByTeam()

        expect(action).toMatchObject({
            [TEAM_ID]: {
                [ACTION_ID]: {
                    id: ACTION_ID,
                    name: 'Test Action',
                    deleted: false,
                    post_to_slack: true,
                    slack_message_format: '',
                    is_calculating: false,
                    steps: [
                        {
                            id: ACTION_STEP_ID,
                            action_id: ACTION_ID,
                            tag_name: null,
                            text: null,
                            href: null,
                            selector: null,
                            url: null,
                            url_matching: null,
                            name: null,
                            event: null,
                            properties: [
                                { type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] },
                            ],
                        },
                    ],
                },
            },
        })
    })

    async function fetchPersonByPersonId(teamId: number, personId: number): Promise<Person> {
        const selectResult = await db.postgresQuery(
            `SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2`,
            [teamId, personId],
            'fetchPersonByPersonId'
        )

        return selectResult.rows[0]
    }

    describe('createPerson', () => {
        let team: Team
        const uuid = new UUIDT().toString()
        const distinctId = 'distinct_id1'

        beforeEach(async () => {
            team = await getFirstTeam(hub)
        })

        test('without properties', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, false, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)

            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('without properties indentified true', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(true)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('with properties', async () => {
            const person = await db.createPerson(
                TIMESTAMP,
                { a: 123, b: false, c: 'bbb' },
                { a: TIMESTAMP.toISO(), b: TIMESTAMP.toISO(), c: TIMESTAMP.toISO() },
                { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set, c: PropertyUpdateOperation.SetOnce },
                team.id,
                null,
                false,
                uuid,
                [distinctId]
            )
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({ a: 123, b: false, c: 'bbb' })
            expect(fetched_person.properties_last_operation).toEqual({
                a: PropertyUpdateOperation.Set,
                b: PropertyUpdateOperation.Set,
                c: PropertyUpdateOperation.SetOnce,
            })
            expect(fetched_person.properties_last_updated_at).toEqual({
                a: TIMESTAMP.toISO(),
                b: TIMESTAMP.toISO(),
                c: TIMESTAMP.toISO(),
            })
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })
    })

    describe('fetchGroupTypes() and insertGroupType()', () => {
        it('fetches group types that have been inserted', async () => {
            expect(await db.fetchGroupTypes(2)).toEqual({})
            expect(await db.insertGroupType(2, 'g0', 0)).toEqual([0, true])
            expect(await db.insertGroupType(2, 'g1', 1)).toEqual([1, true])
            expect(await db.fetchGroupTypes(2)).toEqual({ g0: 0, g1: 1 })
        })

        it('handles conflicting by index when inserting and limits', async () => {
            expect(await db.insertGroupType(2, 'g0', 0)).toEqual([0, true])
            expect(await db.insertGroupType(2, 'g1', 0)).toEqual([1, true])
            expect(await db.insertGroupType(2, 'g2', 0)).toEqual([2, true])
            expect(await db.insertGroupType(2, 'g3', 1)).toEqual([3, true])
            expect(await db.insertGroupType(2, 'g4', 0)).toEqual([4, true])
            expect(await db.insertGroupType(2, 'g5', 0)).toEqual([null, false])
            expect(await db.insertGroupType(2, 'g6', 0)).toEqual([null, false])

            expect(await db.fetchGroupTypes(2)).toEqual({ g0: 0, g1: 1, g2: 2, g3: 3, g4: 4 })
        })

        it('handles conflict by name when inserting', async () => {
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual([0, true])
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual([0, false])
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual([0, false])
            expect(await db.insertGroupType(2, 'foo', 0)).toEqual([1, true])
            expect(await db.insertGroupType(2, 'foo', 0)).toEqual([1, false])

            expect(await db.fetchGroupTypes(2)).toEqual({ group_name: 0, foo: 1 })
        })
    })

    describe('fetchGroup(), insertGroup() and updateGroup()', () => {
        it('returns undefined if no group type exists', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            expect(await db.fetchGroup(3, 0, 'group_key')).toEqual(undefined)
            expect(await db.fetchGroup(2, 1, 'group_key')).toEqual(undefined)
            expect(await db.fetchGroup(2, 1, 'group_key2')).toEqual(undefined)
        })

        it('allows inserts and fetches', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            expect(await db.fetchGroup(2, 0, 'group_key')).toEqual({
                id: expect.any(Number),
                team_id: 2,
                group_type_index: 0,
                group_key: 'group_key',
                group_properties: { prop: 'val' },
                created_at: TIMESTAMP,
                properties_last_updated_at: { prop: TIMESTAMP.toISO() },
                properties_last_operation: { prop: PropertyUpdateOperation.Set },
                version: 1,
            })
        })

        it('insertGroup raises RaceConditionErrors if inserting in parallel', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            await expect(
                db.insertGroup(
                    2,
                    0,
                    'group_key',
                    { prop: 'newval' },
                    TIMESTAMP,
                    { prop: TIMESTAMP.toISO() },
                    { prop: PropertyUpdateOperation.Set },
                    1
                )
            ).rejects.toEqual(new RaceConditionError('Parallel posthog_group inserts, retry'))
        })

        it('handles updates', async () => {
            await db.insertGroup(
                2,
                0,
                'group_key',
                { prop: 'val' },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )

            const originalGroup = await db.fetchGroup(2, 0, 'group_key')

            const timestamp2 = DateTime.fromISO('2000-10-14T12:42:06.502Z').toUTC()
            await db.updateGroup(
                2,
                0,
                'group_key',
                { prop: 'newVal', prop2: 2 },
                TIMESTAMP,
                { prop: timestamp2.toISO(), prop2: timestamp2.toISO() },
                { prop: PropertyUpdateOperation.Set, prop2: PropertyUpdateOperation.Set },
                2
            )

            expect(await db.fetchGroup(2, 0, 'group_key')).toEqual({
                id: originalGroup!.id,
                team_id: 2,
                group_type_index: 0,
                group_key: 'group_key',
                group_properties: { prop: 'newVal', prop2: 2 },
                created_at: TIMESTAMP,
                properties_last_updated_at: { prop: timestamp2.toISO(), prop2: timestamp2.toISO() },
                properties_last_operation: { prop: PropertyUpdateOperation.Set, prop2: PropertyUpdateOperation.Set },
                version: 2,
            })
        })
    })

    describe('addOrUpdatePublicJob', () => {
        it('updates the column if the job name is new', async () => {
            await insertRow(db.postgres, 'posthog_plugin', { ...plugin60, id: 88 })

            const jobName = 'newJob'
            const jobPayload = { foo: 'string' }
            await db.addOrUpdatePublicJob(88, jobName, jobPayload)
            const publicJobs = (
                await db.postgresQuery('SELECT public_jobs FROM posthog_plugin WHERE id = $1', [88], 'testPublicJob1')
            ).rows[0].public_jobs

            expect(publicJobs[jobName]).toEqual(jobPayload)
        })

        it('updates the column if the job payload is new', async () => {
            await insertRow(db.postgres, 'posthog_plugin', { ...plugin60, id: 88, public_jobs: { foo: 'number' } })

            const jobName = 'newJob'
            const jobPayload = { foo: 'string' }
            await db.addOrUpdatePublicJob(88, jobName, jobPayload)
            const publicJobs = (
                await db.postgresQuery('SELECT public_jobs FROM posthog_plugin WHERE id = $1', [88], 'testPublicJob1')
            ).rows[0].public_jobs

            expect(publicJobs[jobName]).toEqual(jobPayload)
        })
    })

    describe('person and group properties on events', () => {
        beforeEach(async () => {
            const redis = await hub.redisPool.acquire()
            const keys = (await redis.keys('person_*')).concat(await redis.keys('group_props*'))
            const promises = []
            for (const key of keys) {
                promises.push(redis.del(key))
            }
            await Promise.all(promises)
            await hub.redisPool.release(redis)
            db.personAndGroupsCachingEnabledTeams.add(2)
            db.PERSONS_AND_GROUPS_CACHE_TTL = 60 * 60 // 1h i.e. keys won't expire during the test
        })

        it('getPersonData works', async () => {
            const uuid = new UUIDT().toString()
            const distinctId = 'distinct_id1'
            await db.createPerson(
                TIMESTAMP,
                { a: 12345, b: false, c: 'bbb' },
                { a: TIMESTAMP.toISO(), b: TIMESTAMP.toISO(), c: TIMESTAMP.toISO() },
                { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set, c: PropertyUpdateOperation.SetOnce },
                2,
                null,
                false,
                uuid,
                [distinctId]
            )
            const res = await db.getPersonData(2, distinctId)
            expect(res?.uuid).toEqual(uuid)
            expect(res?.created_at_iso).toEqual(TIMESTAMP.toISO())
            expect(res?.properties).toEqual({ a: 12345, b: false, c: 'bbb' })
        })

        it('getPersonData works not cached', async () => {
            const uuid = new UUIDT().toString()
            const distinctId = 'distinct_id1'
            db.personAndGroupsCachingEnabledTeams.delete(2) // enabled later, i.e. previous not cached
            await db.createPerson(
                TIMESTAMP,
                { a: 123, b: false, c: 'bbb' },
                { a: TIMESTAMP.toISO(), b: TIMESTAMP.toISO(), c: TIMESTAMP.toISO() },
                { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set, c: PropertyUpdateOperation.SetOnce },
                2,
                null,
                false,
                uuid,
                [distinctId]
            )
            db.personAndGroupsCachingEnabledTeams.add(2)
            const res = await db.getPersonData(2, distinctId)
            expect(res?.uuid).toEqual(uuid)
            expect(res?.created_at_iso).toEqual(TIMESTAMP.toISO())
            expect(res?.properties).toEqual({ a: 123, b: false, c: 'bbb' })
        })

        it('Person props are cached and used from cache', async () => {
            // manually update from the DB and check that we still get the right props, i.e. previous ones
            const uuid = new UUIDT().toString()
            const distinctId = 'distinct_id1'
            await db.createPerson(
                // cached
                TIMESTAMP,
                { a: 333, b: false, c: 'bbb' },
                { a: TIMESTAMP.toISO(), b: TIMESTAMP.toISO(), c: TIMESTAMP.toISO() },
                { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set, c: PropertyUpdateOperation.SetOnce },
                2,
                null,
                false,
                uuid,
                [distinctId]
            )
            await db.postgresQuery(
                // not cached
                `
            UPDATE posthog_person SET properties = $3
            WHERE team_id = $1 AND uuid = $2
            `,
                [2, uuid, JSON.stringify({ prop: 'val-that-isnt-cached' })],
                'testGroupPropertiesOnEvents'
            )
            const res = await db.getPersonData(2, distinctId)
            expect(res?.properties).toEqual({ a: 333, b: false, c: 'bbb' })
        })

        it('Gets the right group properties', async () => {
            await db.insertGroup(
                // would get cached
                2,
                0,
                'group_key',
                { prop: 'val', num: 1234 },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )
            await db.postgresQuery(
                // not cached
                `
            INSERT INTO posthog_group (team_id, group_key, group_type_index, group_properties, created_at, properties_last_updated_at, properties_last_operation, version)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            `,
                [
                    2,
                    'g2',
                    2,
                    JSON.stringify({ p2: 'p2val' }),
                    TIMESTAMP,
                    JSON.stringify({ p2: TIMESTAMP.toISO() }),
                    JSON.stringify({ p2: PropertyUpdateOperation.Set }),
                    1,
                ],
                'testGroupPropertiesOnEvents'
            )
            const res = await db.getGroupProperties(2, [
                { index: 0, key: 'group_key' },
                { index: 2, key: 'g2' },
                { index: 3, key: 'no-such-group' },
            ])
            expect(res).toEqual({
                group0_properties: '{"prop":"val","num":1234}',
                group2_properties: '{"p2":"p2val"}',
                group3_properties: '{}',
            })
        })

        it('Group props are cached and used from cache', async () => {
            // manually update from the DB and check that we still get the right props, i.e. previous ones
            await db.insertGroup(
                // would get cached
                2,
                0,
                'group_key',
                { prop: 'val', num: 1234567 },
                TIMESTAMP,
                { prop: TIMESTAMP.toISO() },
                { prop: PropertyUpdateOperation.Set },
                1
            )
            await db.postgresQuery(
                // not cached
                `
            UPDATE posthog_group SET group_properties = $4
            WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3
            `,
                [2, 0, 'group_key', JSON.stringify({ prop: 'val-that-isnt-cached' })],
                'testGroupPropertiesOnEvents'
            )
            const res = await db.getGroupProperties(2, [{ index: 0, key: 'group_key' }])
            expect(res).toEqual({
                group0_properties: '{"prop":"val","num":1234567}',
            })
        })
    })

    describe('getPluginSource', () => {
        let team: Team
        let plugin: number

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            const plug = await db.postgresQuery(
                'INSERT INTO posthog_plugin (name, organization_id, config_schema, from_json, from_web, is_global, is_preinstalled, is_stateless, created_at, capabilities) values($1, $2, $3, false, false, false, false, false, $4, $5) RETURNING id',
                ['My Plug', team.organization_id, [], new Date(), {}],
                ''
            )
            plugin = plug.rows[0].id
        })

        test('fetches from the database', async () => {
            let source = await db.getPluginSource(plugin, 'index.ts')
            expect(source).toBe(null)

            await db.postgresQuery(
                'INSERT INTO posthog_pluginsourcefile (id, plugin_id, filename, source) values($1, $2, $3, $4)',
                [new UUIDT().toString(), plugin, 'index.ts', 'USE THE SOURCE'],
                ''
            )

            source = await db.getPluginSource(plugin, 'index.ts')
            expect(source).toBe('USE THE SOURCE')
        })
    })

    describe('fetchInstanceSetting & upsertInstanceSetting', () => {
        it('fetch returns null by default', async () => {
            const result = await db.fetchInstanceSetting('SOME_SETTING')
            expect(result).toEqual(null)
        })

        it('can create and update settings', async () => {
            await db.upsertInstanceSetting('SOME_SETTING', 'some_value')
            expect(await db.fetchInstanceSetting('SOME_SETTING')).toEqual('some_value')

            await db.upsertInstanceSetting('SOME_SETTING', 'new_value')
            expect(await db.fetchInstanceSetting('SOME_SETTING')).toEqual('new_value')
        })

        it('handles different types', async () => {
            await db.upsertInstanceSetting('NUMERIC_SETTING', 56)
            await db.upsertInstanceSetting('BOOLEAN_SETTING', true)

            expect(await db.fetchInstanceSetting('NUMERIC_SETTING')).toEqual(56)
            expect(await db.fetchInstanceSetting('BOOLEAN_SETTING')).toEqual(true)
        })
    })
})
