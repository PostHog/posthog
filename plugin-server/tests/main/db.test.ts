import { DateTime } from 'luxon'

import { Hub, Person, PropertyOperator, PropertyUpdateOperation, Team, TimestampFormat } from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { createHub } from '../../src/utils/db/hub'
import { generateKafkaPersonUpdateMessage } from '../../src/utils/db/utils'
import { castTimestampOrNow, RaceConditionError, UUIDT } from '../../src/utils/utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { getFirstTeam, insertRow, resetTestDatabase } from '../helpers/sql'
import { POSTGRES_QUERY_CACHE_PREFIX } from './../../src/utils/db/db'
import { plugin60 } from './../helpers/plugins'

jest.mock('../../src/utils/status')

describe('DB', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        db = hub.db
    })

    afterEach(async () => {
        await closeServer()
        jest.clearAllMocks()
    })

    const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()

    describe('fetchAllActionsGroupedByTeam() and fetchAction()', () => {
        beforeEach(async () => {
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
            })
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
            await insertRow(hub.db.postgres, 'posthog_actionstep', {
                id: 913,
                action_id: 69,
                tag_name: null,
                text: null,
                href: null,
                selector: null,
                url: null,
                url_matching: null,
                name: null,
                event: null,
                properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
            })

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
                        steps: [
                            {
                                id: 913,
                                action_id: 69,
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
                        hooks: [],
                    },
                },
            })

            const action = await db.fetchAction(69)
            expect(action!.steps).toEqual([
                {
                    id: 913,
                    action_id: 69,
                    tag_name: null,
                    text: null,
                    href: null,
                    selector: null,
                    url: null,
                    url_matching: null,
                    name: null,
                    event: null,
                    properties: [{ type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] }],
                },
            ])
        })

        it('returns actions with correct `ee_hook`', async () => {
            await hub.db.postgres.query('UPDATE posthog_action SET post_to_slack = false')
            await insertRow(hub.db.postgres, 'ee_hook', {
                id: 'abc',
                team_id: 2,
                user_id: 1001,
                resource_id: 69,
                event: 'action_performed',
                target: 'https://rest-hooks.example.com/',
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
                                target: 'https://rest-hooks.example.com/',
                            },
                        ],
                    },
                },
            })

            expect(await db.fetchAction(69)).toEqual(result[2][69])
        })

        it('does not return actions that dont match conditions', async () => {
            await hub.db.postgres.query('UPDATE posthog_action SET post_to_slack = false')

            const result = await db.fetchAllActionsGroupedByTeam()
            expect(result).toEqual({})

            expect(await db.fetchAction(69)).toEqual(null)
        })

        it('does not return actions which are deleted', async () => {
            await hub.db.postgres.query('UPDATE posthog_action SET deleted = true')

            const result = await db.fetchAllActionsGroupedByTeam()
            expect(result).toEqual({})

            expect(await db.fetchAction(69)).toEqual(null)
        })

        it('does not return actions with incorrect ee_hook', async () => {
            await hub.db.postgres.query('UPDATE posthog_action SET post_to_slack = false')
            await insertRow(hub.db.postgres, 'ee_hook', {
                id: 'abc',
                team_id: 2,
                user_id: 1001,
                resource_id: 69,
                event: 'event_performed',
                target: 'https://rest-hooks.example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            })
            await insertRow(hub.db.postgres, 'ee_hook', {
                id: 'efg',
                team_id: 2,
                user_id: 1001,
                resource_id: 70,
                event: 'event_performed',
                target: 'https://rest-hooks.example.com/',
                created: new Date().toISOString(),
                updated: new Date().toISOString(),
            })

            const result = await db.fetchAllActionsGroupedByTeam()
            expect(result).toEqual({})

            expect(await db.fetchAction(69)).toEqual(null)
        })

        describe('FOSS', () => {
            beforeEach(async () => {
                await hub.db.postgres.query('ALTER TABLE ee_hook RENAME TO ee_hook_backup')
            })

            afterEach(async () => {
                await hub.db.postgres.query('ALTER TABLE ee_hook_backup RENAME TO ee_hook')
            })

            it('does not blow up', async () => {
                await hub.db.postgres.query('UPDATE posthog_action SET post_to_slack = false')

                const result = await db.fetchAllActionsGroupedByTeam()
                expect(result).toEqual({})
                expect(await db.fetchAction(69)).toEqual(null)
            })
        })
    })

    async function fetchPersonByPersonId(teamId: number, personId: number): Promise<Person | undefined> {
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

            expect(fetched_person!.is_identified).toEqual(false)
            expect(fetched_person!.properties).toEqual({})
            expect(fetched_person!.properties_last_operation).toEqual({})
            expect(fetched_person!.properties_last_updated_at).toEqual({})
            expect(fetched_person!.uuid).toEqual(uuid)
            expect(fetched_person!.team_id).toEqual(team.id)
        })

        test('without properties indentified true', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person!.is_identified).toEqual(true)
            expect(fetched_person!.properties).toEqual({})
            expect(fetched_person!.properties_last_operation).toEqual({})
            expect(fetched_person!.properties_last_updated_at).toEqual({})
            expect(fetched_person!.uuid).toEqual(uuid)
            expect(fetched_person!.team_id).toEqual(team.id)
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
            expect(fetched_person!.is_identified).toEqual(false)
            expect(fetched_person!.properties).toEqual({ a: 123, b: false, c: 'bbb' })
            expect(fetched_person!.properties_last_operation).toEqual({
                a: PropertyUpdateOperation.Set,
                b: PropertyUpdateOperation.Set,
                c: PropertyUpdateOperation.SetOnce,
            })
            expect(fetched_person!.properties_last_updated_at).toEqual({
                a: TIMESTAMP.toISO(),
                b: TIMESTAMP.toISO(),
                c: TIMESTAMP.toISO(),
            })
            expect(fetched_person!.uuid).toEqual(uuid)
            expect(fetched_person!.team_id).toEqual(team.id)
        })
    })

    describe('updatePerson', () => {
        it('Clickhouse and Postgres are in sync if multiple updates concurrently', async () => {
            jest.spyOn(db.kafkaProducer!, 'queueMessage')
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const distinctId = 'distinct_id1'
            // Note that we update the person badly in case of concurrent updates, but lets make sure we're consistent
            const personDbBefore = await db.createPerson(TIMESTAMP, { c: 'aaa' }, {}, {}, team.id, null, false, uuid, [
                distinctId,
            ])
            const providedPersonTs = DateTime.fromISO('2000-04-04T11:42:06.502Z').toUTC()
            const personProvided = { ...personDbBefore, properties: { c: 'bbb' }, created_at: providedPersonTs }
            const updateTs = DateTime.fromISO('2000-04-04T11:42:06.502Z').toUTC()
            const update = { created_at: updateTs }
            const [updatedPerson] = await db.updatePersonDeprecated(personProvided, update)

            // verify we have the correct update in Postgres db
            const personDbAfter = await fetchPersonByPersonId(personDbBefore.team_id, personDbBefore.id)
            expect(personDbAfter!.created_at).toEqual(updateTs.toISO())
            // we didn't change properties so they should be what was in the db
            expect(personDbAfter!.properties).toEqual({ c: 'aaa' })

            //verify we got the expected updated person back
            expect(updatedPerson.created_at).toEqual(updateTs)
            expect(updatedPerson.properties).toEqual({ c: 'aaa' })

            // verify correct Kafka message was sent
            const expected_message = generateKafkaPersonUpdateMessage(
                updateTs,
                { c: 'aaa' },
                personDbBefore.team_id,
                personDbBefore.is_identified,
                personDbBefore.uuid,
                1
            )
            expect(db.kafkaProducer!.queueMessage).toHaveBeenLastCalledWith(expected_message)
        })
    })

    describe('deletePerson', () => {
        jest.setTimeout(60000)

        const uuid = new UUIDT().toString()
        it('deletes person from postgres', async () => {
            const team = await getFirstTeam(hub)
            // :TRICKY: We explicitly don't create distinct_ids here to keep the deletion process simpler.
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [])

            await db.deletePerson(person)

            const fetchedPerson = await fetchPersonByPersonId(team.id, person.id)
            expect(fetchedPerson).toEqual(undefined)
        })

        describe('clickhouse behavior', () => {
            beforeEach(async () => {
                await resetTestDatabaseClickhouse()
                // :TRICKY: Avoid collapsing rows before we are able to read them in the below tests.
                await db.clickhouseQuery('SYSTEM STOP MERGES')
            })

            afterEach(async () => {
                await db.clickhouseQuery('SYSTEM START MERGES')
            })

            async function fetchPersonsRows(options: { final?: boolean } = {}) {
                const query = `SELECT * FROM person ${options.final ? 'FINAL' : ''} WHERE id = '${uuid}'`
                return (await db.clickhouseQuery(query)).data
            }

            it('marks person as deleted in clickhouse', async () => {
                const team = await getFirstTeam(hub)
                // :TRICKY: We explicitly don't create distinct_ids here to keep the deletion process simpler.
                const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [])
                await delayUntilEventIngested(fetchPersonsRows, 1)

                // We do an update to verify
                await db.updatePersonDeprecated(person, { properties: { foo: 'bar' } })
                await db.kafkaProducer.flush()
                await delayUntilEventIngested(fetchPersonsRows, 2)

                const kafkaMessages = await db.deletePerson(person)
                await db.kafkaProducer.queueMessages(kafkaMessages)
                await db.kafkaProducer.flush()

                const persons = await delayUntilEventIngested(fetchPersonsRows, 3)

                expect(persons).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            id: uuid,
                            properties: JSON.stringify({}),
                            is_deleted: 0,
                            version: 0,
                        }),
                        expect.objectContaining({
                            id: uuid,
                            properties: JSON.stringify({ foo: 'bar' }),
                            is_deleted: 0,
                            version: 1,
                        }),
                        expect.objectContaining({
                            id: uuid,
                            is_deleted: 1,
                            version: 101,
                        }),
                    ])
                )

                const personsFinal = await fetchPersonsRows({ final: true })
                expect(personsFinal).toEqual(
                    expect.arrayContaining([
                        expect.objectContaining({
                            id: uuid,
                            is_deleted: 1,
                            version: 101,
                        }),
                    ])
                )
            })
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
            const keys = (await redis.keys('person_*')).concat(await redis.keys('group_*'))
            const promises: Promise<number>[] = []
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
            expect(res?.created_at.toISO()).toEqual(TIMESTAMP.toUTC().toISO())
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
            expect(res?.created_at.toISO()).toEqual(TIMESTAMP.toUTC().toISO())
            expect(res?.properties).toEqual({ a: 123, b: false, c: 'bbb' })
        })

        it('person props are cached and used from cache', async () => {
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

        it('gets the right group properties', async () => {
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
            const res = await db.getPropertiesForGroups(2, [
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

        it('group props are cached and used from cache', async () => {
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
            const res = await db.getPropertiesForGroups(2, [{ index: 0, key: 'group_key' }])
            expect(res).toEqual({
                group0_properties: '{"prop":"val","num":1234567}',
            })
        })

        it('gets created_at from DB if cache does not exist', async () => {
            jest.spyOn(db, 'getGroupsCreatedAtFromDbAndUpdateCache')

            await db.insertGroup(2, 0, 'g0', {}, TIMESTAMP, {}, {}, 1, undefined, { cache: false })
            await db.insertGroup(2, 1, 'g1', {}, TIMESTAMP.minus(1), {}, {}, 1, undefined, { cache: false })
            await db.insertGroup(2, 2, 'g2', {}, TIMESTAMP.minus(2), {}, {}, 1, undefined, { cache: false })
            await db.insertGroup(2, 3, 'g3', {}, TIMESTAMP.minus(3), {}, {}, 1, undefined, { cache: false })
            await db.insertGroup(2, 4, 'g4', {}, TIMESTAMP.minus(4), {}, {}, 1, undefined, { cache: false })

            const res = await db.getCreatedAtForGroups(2, [
                { index: 0, key: 'g0' },
                { index: 1, key: 'g1' },
                { index: 2, key: 'g2' },
                { index: 4, key: 'g4' },
            ])

            expect(res).toEqual({
                group0_created_at: castTimestampOrNow(TIMESTAMP, TimestampFormat.ClickHouse),
                group1_created_at: castTimestampOrNow(TIMESTAMP.minus(1), TimestampFormat.ClickHouse),
                group2_created_at: castTimestampOrNow(TIMESTAMP.minus(2), TimestampFormat.ClickHouse),
                group4_created_at: castTimestampOrNow(TIMESTAMP.minus(4), TimestampFormat.ClickHouse),
            })

            expect(db.getGroupsCreatedAtFromDbAndUpdateCache).toHaveBeenCalled()
        })

        it('group created_at is cached and used from cache', async () => {
            jest.spyOn(db, 'getGroupsCreatedAtFromDbAndUpdateCache')

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
            UPDATE posthog_group SET created_at = now()
            WHERE team_id = $1 AND group_type_index = $2 AND group_key = $3
            `,
                [2, 0, 'group_key'],
                'testGroupCreatedAtOnEvents'
            )
            const res = await db.getCreatedAtForGroups(2, [{ index: 0, key: 'group_key' }])
            expect(res).toEqual({
                group0_created_at: castTimestampOrNow(TIMESTAMP, TimestampFormat.ClickHouse),
            })
            expect(db.getGroupsCreatedAtFromDbAndUpdateCache).not.toHaveBeenCalled()
        })
    })

    describe('postgresQuery', () => {
        it('caches query results if cacheResult=true', async () => {
            jest.spyOn(db, 'redisSet')
            const queryTag = 'testCachedQuery'
            await db.postgresQuery('SELECT 1 as col', undefined, queryTag, undefined, true)
            expect(db.redisSet).toHaveBeenCalledWith(
                `${POSTGRES_QUERY_CACHE_PREFIX}${queryTag}`,
                JSON.stringify({ rows: [{ col: 1 }], rowCount: 1 }),
                expect.any(Number)
            )
        })

        it('returns cached results if cacheResult=true', async () => {
            const queryTag = 'testCachedQuery'
            await db.postgresQuery('SELECT 1 as col', undefined, queryTag, undefined, true)
            const res = await db.postgresQuery('SELECT 2 as col', undefined, queryTag, undefined, true)

            // if this wasn't cached the value would have been 2
            expect(res.rows[0].col).toEqual(1)
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

    describe('addFeatureFlagHashKeysForMergedPerson()', () => {
        let team: Team
        let sourcePersonID: Person['id']
        let targetPersonID: Person['id']

        async function getAllHashKeyOverrides(): Promise<any> {
            const result = await db.postgresQuery(
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride',
                [],
                ''
            )
            return result.rows
        }

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            const sourcePerson = await db.createPerson(
                TIMESTAMP,
                {},
                {},
                {},
                team.id,
                null,
                false,
                new UUIDT().toString(),
                ['source_person']
            )
            const targetPerson = await db.createPerson(
                TIMESTAMP,
                {},
                {},
                {},
                team.id,
                null,
                false,
                new UUIDT().toString(),
                ['target_person']
            )
            sourcePersonID = sourcePerson.id
            targetPersonID = targetPerson.id
        })

        it("doesn't fail on empty data", async () => {
            await db.addFeatureFlagHashKeysForMergedPerson(team.id, sourcePersonID, targetPersonID)
        })

        it('updates all valid keys when target person had no overrides', async () => {
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })

            await db.addFeatureFlagHashKeysForMergedPerson(team.id, sourcePersonID, targetPersonID)

            const result = await getAllHashKeyOverrides()

            expect(result.length).toEqual(2)
            expect(result).toEqual(
                expect.arrayContaining([
                    {
                        feature_flag_key: 'aloha',
                        hash_key: 'override_value_for_aloha',
                        person_id: targetPersonID,
                    },
                    {
                        feature_flag_key: 'beta-feature',
                        hash_key: 'override_value_for_beta_feature',
                        person_id: targetPersonID,
                    },
                ])
            )
        })

        it('updates all valid keys when conflicts with target person', async () => {
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'existing_override_value_for_beta_feature',
            })

            await db.addFeatureFlagHashKeysForMergedPerson(team.id, sourcePersonID, targetPersonID)

            const result = await getAllHashKeyOverrides()

            expect(result.length).toEqual(2)
            expect(result).toEqual(
                expect.arrayContaining([
                    {
                        feature_flag_key: 'beta-feature',
                        hash_key: 'existing_override_value_for_beta_feature',
                        person_id: targetPersonID,
                    },
                    {
                        feature_flag_key: 'aloha',
                        hash_key: 'override_value_for_aloha',
                        person_id: targetPersonID,
                    },
                ])
            )
        })

        it('updates nothing when target person overrides exist', async () => {
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })

            await db.addFeatureFlagHashKeysForMergedPerson(team.id, sourcePersonID, targetPersonID)

            const result = await getAllHashKeyOverrides()

            expect(result.length).toEqual(2)
            expect(result).toEqual(
                expect.arrayContaining([
                    {
                        feature_flag_key: 'aloha',
                        hash_key: 'override_value_for_aloha',
                        person_id: targetPersonID,
                    },
                    {
                        feature_flag_key: 'beta-feature',
                        hash_key: 'override_value_for_beta_feature',
                        person_id: targetPersonID,
                    },
                ])
            )
        })
    })
})
