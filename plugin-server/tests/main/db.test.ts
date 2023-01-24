import { DateTime } from 'luxon'

import {
    ClickHouseTimestamp,
    Cohort,
    Hub,
    Person,
    PropertyOperator,
    PropertyUpdateOperation,
    Team,
} from '../../src/types'
import { DB, GroupId } from '../../src/utils/db/db'
import { createHub } from '../../src/utils/db/hub'
import { generateKafkaPersonUpdateMessage } from '../../src/utils/db/utils'
import { RaceConditionError, UUIDT } from '../../src/utils/utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../helpers/clickhouse'
import { createOrganization, createTeam, getFirstTeam, insertRow, resetTestDatabase } from '../helpers/sql'
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
    const CLICKHOUSE_TIMESTAMP = '2000-10-14 11:42:06.502' as ClickHouseTimestamp

    function fetchGroupCache(teamId: number, groupTypeIndex: number, groupKey: string) {
        return db.redisGet(db.getGroupDataCacheKey(teamId, groupTypeIndex, groupKey), null)
    }

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

    describe('fetchPerson()', () => {
        it('returns undefined if person does not exist', async () => {
            const team = await getFirstTeam(hub)
            const person = await hub.db.fetchPerson(team.id, 'some_id')

            expect(person).toEqual(undefined)
        })

        it('returns person object if person exists', async () => {
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const createdPerson = await db.createPerson(TIMESTAMP, { foo: 'bar' }, {}, {}, team.id, null, true, uuid, [
                'some_id',
            ])

            const person = await db.fetchPerson(team.id, 'some_id')

            expect(person).toEqual(createdPerson)
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(Number),
                    uuid: uuid.toString(),
                    properties: { foo: 'bar' },
                    is_identified: true,
                    created_at: TIMESTAMP,
                    version: 0,
                })
            )
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

        describe('with caching', () => {
            it('insertGroup() and updateGroup() update cache', async () => {
                expect(await fetchGroupCache(2, 0, 'group_key')).toEqual(null)

                await db.insertGroup(
                    2,
                    0,
                    'group_key',
                    { prop: 'val' },
                    TIMESTAMP,
                    { prop: TIMESTAMP.toISO() },
                    { prop: PropertyUpdateOperation.Set },
                    1,
                    undefined,
                    { cache: true }
                )

                expect(await fetchGroupCache(2, 0, 'group_key')).toEqual({
                    created_at: CLICKHOUSE_TIMESTAMP,
                    properties: { prop: 'val' },
                })

                await db.updateGroup(
                    2,
                    0,
                    'group_key',
                    { prop: 'newVal', prop2: 2 },
                    TIMESTAMP,
                    { prop: TIMESTAMP.toISO(), prop2: TIMESTAMP.toISO() },
                    { prop: PropertyUpdateOperation.Set, prop2: PropertyUpdateOperation.Set },
                    2
                )

                expect(await fetchGroupCache(2, 0, 'group_key')).toEqual({
                    created_at: CLICKHOUSE_TIMESTAMP,
                    properties: { prop: 'newVal', prop2: 2 },
                })
            })
        })
    })

    describe('updateGroupCache()', () => {
        it('updates redis', async () => {
            await db.updateGroupCache(2, 0, 'group_key', {
                created_at: CLICKHOUSE_TIMESTAMP,
                properties: { prop: 'val' },
            })

            expect(await fetchGroupCache(2, 0, 'group_key')).toEqual({
                created_at: CLICKHOUSE_TIMESTAMP,
                properties: { prop: 'val' },
            })
        })
    })

    describe('getGroupsColumns()', () => {
        beforeEach(() => {
            jest.spyOn(db, 'fetchGroup')
            jest.spyOn(db, 'redisGet')
            db.statsd = { increment: jest.fn(), timing: jest.fn() } as any
        })

        describe('one group', () => {
            it('tries to fetch data from the cache first, avoiding the database', async () => {
                await db.updateGroupCache(2, 0, 'group_key', {
                    properties: { foo: 'bar' },
                    created_at: CLICKHOUSE_TIMESTAMP,
                })

                const result = await db.getGroupsColumns(2, [[0, 'group_key']])
                expect(result).toEqual({
                    group0_properties: JSON.stringify({ foo: 'bar' }),
                    group0_created_at: CLICKHOUSE_TIMESTAMP,
                })

                expect(db.fetchGroup).not.toHaveBeenCalled()
            })

            it('tries to fetch data from Postgres if Redis is down', async () => {
                await db.insertGroup(2, 0, 'group_key', { foo: 'bar' }, TIMESTAMP, {}, {}, 0, undefined, {
                    cache: false,
                })

                jest.spyOn(db, 'redisGet').mockRejectedValue(new Error())

                const result = await db.getGroupsColumns(2, [[0, 'group_key']])

                expect(result).toEqual({
                    group0_properties: JSON.stringify({ foo: 'bar' }),
                    group0_created_at: CLICKHOUSE_TIMESTAMP,
                })
                expect(db.fetchGroup).toHaveBeenCalled()
            })

            it('tries to fetch data from Postgres if there is no cached data', async () => {
                await db.insertGroup(2, 0, 'group_key', { foo: 'bar' }, TIMESTAMP, {}, {}, 0, undefined, {
                    cache: false,
                })

                const result = await db.getGroupsColumns(2, [[0, 'group_key']])

                expect(result).toEqual({
                    group0_properties: JSON.stringify({ foo: 'bar' }),
                    group0_created_at: CLICKHOUSE_TIMESTAMP,
                })
                expect(db.fetchGroup).toHaveBeenCalled()
            })

            it('triggers a statsd metric if the data doesnt exist in Postgres or Redis', async () => {
                await db.getGroupsColumns(2, [[0, 'unknown_key']])

                expect(db.statsd?.increment).toHaveBeenLastCalledWith('groups_data_missing_entirely')
            })
        })

        describe('multiple groups', () => {
            it('fetches data from cache for some groups and postgres for others', async () => {
                const groupIds: GroupId[] = [
                    [0, '0'],
                    [1, '1'],
                    [2, '2'],
                    [3, '3'],
                    [4, '4'],
                ]

                for (const [groupTypeIndex, groupKey] of [groupIds[0], groupIds[3]]) {
                    await db.updateGroupCache(2, groupTypeIndex, groupKey, {
                        properties: { cached: true },
                        created_at: CLICKHOUSE_TIMESTAMP,
                    })
                }

                for (const [groupTypeIndex, groupKey] of groupIds) {
                    await db.insertGroup(
                        2,
                        groupTypeIndex,
                        groupKey,
                        { cached: false },
                        TIMESTAMP,
                        {},
                        {},
                        0,
                        undefined,
                        { cache: false }
                    )
                }
                const result = await db.getGroupsColumns(2, [
                    [0, '0'],
                    [1, '1'],
                    [2, '2'],
                    [3, '3'],
                    [4, '4'],
                ])

                // verify that the first and fourth calls have cached=true and all other have cached=false
                expect(result).toEqual({
                    group0_created_at: CLICKHOUSE_TIMESTAMP,
                    group0_properties: JSON.stringify({
                        cached: true,
                    }),
                    group1_created_at: CLICKHOUSE_TIMESTAMP,
                    group1_properties: JSON.stringify({
                        cached: false,
                    }),
                    group2_created_at: CLICKHOUSE_TIMESTAMP,
                    group2_properties: JSON.stringify({
                        cached: false,
                    }),
                    group3_created_at: CLICKHOUSE_TIMESTAMP,
                    group3_properties: JSON.stringify({
                        cached: true,
                    }),
                    group4_created_at: CLICKHOUSE_TIMESTAMP,
                    group4_properties: JSON.stringify({
                        cached: false,
                    }),
                })

                expect(db.redisGet).toHaveBeenCalledTimes(5)
                expect(db.fetchGroup).toHaveBeenCalledTimes(3)
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
        async function clearCache() {
            const redis = await hub.redisPool.acquire()
            const keys = (await redis.keys('person_*')).concat(await redis.keys('group_*'))
            const promises: Promise<number>[] = []
            for (const key of keys) {
                promises.push(redis.del(key))
            }
            await Promise.all(promises)
            await hub.redisPool.release(redis)
        }

        beforeEach(async () => {
            await clearCache()
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
            await clearCache()
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

    describe('doesPersonBelongToCohort()', () => {
        let team: Team
        let cohort: Cohort
        let person: Person

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            cohort = await hub.db.createCohort({
                name: 'testCohort',
                description: '',
                team_id: team.id,
                version: 10,
            })
            person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, false, new UUIDT().toString(), [])
        })

        it('returns false if person does not belong to cohort', async () => {
            const cohort2 = await hub.db.createCohort({
                name: 'testCohort2',
                description: '',
                team_id: team.id,
            })
            await hub.db.addPersonToCohort(cohort2.id, person.id, cohort.version)

            expect(await hub.db.doesPersonBelongToCohort(cohort.id, person)).toEqual(false)
        })

        it('returns true if person belongs to cohort', async () => {
            await hub.db.addPersonToCohort(cohort.id, person.id, cohort.version)

            expect(await hub.db.doesPersonBelongToCohort(cohort.id, person)).toEqual(true)
        })

        it('returns false if person does not belong to current version of the cohort', async () => {
            await hub.db.addPersonToCohort(cohort.id, person.id, -1)

            expect(await hub.db.doesPersonBelongToCohort(cohort.id, person)).toEqual(false)
        })

        it('handles NULL version cohorts', async () => {
            const cohort2 = await hub.db.createCohort({
                name: 'null_cohort',
                description: '',
                team_id: team.id,
                version: null,
            })
            expect(await hub.db.doesPersonBelongToCohort(cohort2.id, person)).toEqual(false)

            await hub.db.addPersonToCohort(cohort2.id, person.id, null)
            expect(await hub.db.doesPersonBelongToCohort(cohort2.id, person)).toEqual(true)
        })
    })

    describe('fetchTeam()', () => {
        it('fetches a team by id', async () => {
            const organizationId = await createOrganization(db.postgres)
            const teamId = await createTeam(db.postgres, organizationId, 'token1')

            const fetchedTeam = await hub.db.fetchTeam(teamId)
            expect(fetchedTeam).toEqual({
                anonymize_ips: false,
                api_token: 'token1',
                id: teamId,
                ingested_event: true,
                name: 'TEST PROJECT',
                organization_id: organizationId,
                session_recording_opt_in: true,
                slack_incoming_webhook: null,
                uuid: expect.any(String),
            })
        })

        it('returns null if the team does not exist', async () => {
            const fetchedTeam = await hub.db.fetchTeam(99999)
            expect(fetchedTeam).toEqual(null)
        })
    })

    describe('fetchTeamByToken()', () => {
        it('fetches a team by token', async () => {
            const organizationId = await createOrganization(db.postgres)
            const teamId = await createTeam(db.postgres, organizationId, 'token2')

            const fetchedTeam = await hub.db.fetchTeamByToken('token2')
            expect(fetchedTeam).toEqual({
                anonymize_ips: false,
                api_token: 'token2',
                id: teamId,
                ingested_event: true,
                name: 'TEST PROJECT',
                organization_id: organizationId,
                session_recording_opt_in: true,
                slack_incoming_webhook: null,
                uuid: expect.any(String),
            })
        })

        it('returns null if the team does not exist', async () => {
            const fetchedTeam = await hub.db.fetchTeamByToken('token2')
            expect(fetchedTeam).toEqual(null)
        })
    })
})
