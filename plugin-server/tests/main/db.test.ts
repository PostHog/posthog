import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { defaultConfig } from '../../src/config/config'
import {
    BasePerson,
    Hub,
    InternalPerson,
    Person,
    PropertyOperator,
    PropertyUpdateOperation,
    RawAction,
    Team,
} from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { DependencyUnavailableError, RedisOperationError } from '../../src/utils/db/error'
import { closeHub, createHub } from '../../src/utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../src/utils/db/postgres'
import { generateKafkaPersonUpdateMessage } from '../../src/utils/db/utils'
import { RaceConditionError, UUIDT } from '../../src/utils/utils'
import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../helpers/clickhouse'
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

    const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
    const ISO_TIMESTAMP = TIMESTAMP.toISO()!

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

    async function fetchPersonByPersonId(teamId: number, personId: InternalPerson['id']): Promise<Person | undefined> {
        const selectResult = await db.postgres.query(
            PostgresUse.PERSONS_WRITE,
            `SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2`,
            [teamId, personId],
            'fetchPersonByPersonId'
        )

        return selectResult.rows[0]
    }

    test('addPersonlessDistinctId', async () => {
        const team = await getFirstTeam(hub)
        await db.addPersonlessDistinctId(team.id, 'addPersonlessDistinctId')

        // This will conflict, but shouldn't throw an error
        await db.addPersonlessDistinctId(team.id, 'addPersonlessDistinctId')

        const result = await db.postgres.query(
            PostgresUse.PERSONS_WRITE,
            'SELECT id FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2',
            [team.id, 'addPersonlessDistinctId'],
            'addPersonlessDistinctId'
        )

        expect(result.rows.length).toEqual(1)
    })

    describe('createPerson', () => {
        let team: Team
        const uuid = new UUIDT().toString()
        const distinctId = 'distinct_id1'

        beforeEach(async () => {
            team = await getFirstTeam(hub)
        })

        test('without properties', async () => {
            const [person, kafkaMessages] = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, false, uuid, [
                { distinctId },
            ])
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)
            const fetched_person = (await fetchPersonByPersonId(team.id, person.id))! as unknown as BasePerson

            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('without properties indentified true', async () => {
            const [person, kafkaMessages] = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [
                { distinctId },
            ])
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)
            const fetched_person = (await fetchPersonByPersonId(team.id, person.id))! as unknown as BasePerson

            expect(fetched_person.is_identified).toEqual(true)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('with properties', async () => {
            const [person, kafkaMessages] = await db.createPerson(
                TIMESTAMP,
                { a: 123, b: false, c: 'bbb' },
                { a: ISO_TIMESTAMP, b: ISO_TIMESTAMP, c: ISO_TIMESTAMP },
                { a: PropertyUpdateOperation.Set, b: PropertyUpdateOperation.Set, c: PropertyUpdateOperation.SetOnce },
                team.id,
                null,
                false,
                uuid,
                [{ distinctId }]
            )
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)
            const fetched_person = (await fetchPersonByPersonId(team.id, person.id))! as unknown as BasePerson

            expect(fetched_person!.is_identified).toEqual(false)
            expect(fetched_person!.properties).toEqual({ a: 123, b: false, c: 'bbb' })
            expect(fetched_person!.properties_last_operation).toEqual({
                a: PropertyUpdateOperation.Set,
                b: PropertyUpdateOperation.Set,
                c: PropertyUpdateOperation.SetOnce,
            })
            expect(fetched_person!.properties_last_updated_at).toEqual({
                a: ISO_TIMESTAMP,
                b: ISO_TIMESTAMP,
                c: ISO_TIMESTAMP,
            })
            expect(fetched_person!.uuid).toEqual(uuid)
            expect(fetched_person!.team_id).toEqual(team.id)
        })
    })

    describe('updatePerson', () => {
        it('Clickhouse and Postgres are in sync if multiple updates concurrently', async () => {
            jest.spyOn(db.kafkaProducer!, 'queueMessages')
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const distinctId = 'distinct_id1'
            // Note that we update the person badly in case of concurrent updates, but lets make sure we're consistent
            const [personDbBefore, kafkaMessagesPersonDbBefore] = await db.createPerson(
                TIMESTAMP,
                { c: 'aaa' },
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [{ distinctId }]
            )
            await hub.db.kafkaProducer.queueMessages(kafkaMessagesPersonDbBefore)
            const providedPersonTs = DateTime.fromISO('2000-04-04T11:42:06.502Z').toUTC()
            const personProvided = { ...personDbBefore, properties: { c: 'bbb' }, created_at: providedPersonTs }
            const updateTs = DateTime.fromISO('2000-04-04T11:42:06.502Z').toUTC()
            const update = { created_at: updateTs }
            const [updatedPerson, kafkaMessages] = await db.updatePerson(personProvided, update)
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)

            // verify we have the correct update in Postgres db
            const personDbAfter = await fetchPersonByPersonId(personDbBefore.team_id, personDbBefore.id)
            expect(personDbAfter!.created_at).toEqual(updateTs.toISO())
            // we didn't change properties so they should be what was in the db
            expect(personDbAfter!.properties).toEqual({ c: 'aaa' })

            //verify we got the expected updated person back
            expect(updatedPerson.created_at).toEqual(updateTs)
            expect(updatedPerson.properties).toEqual({ c: 'aaa' })

            // verify correct Kafka message was sent
            expect(db.kafkaProducer!.queueMessages).toHaveBeenLastCalledWith([
                generateKafkaPersonUpdateMessage(updatedPerson),
            ])
        })
    })

    describe('deletePerson', () => {
        jest.setTimeout(60000)

        const uuid = new UUIDT().toString()
        it('deletes person from postgres', async () => {
            const team = await getFirstTeam(hub)
            // :TRICKY: We explicitly don't create distinct_ids here to keep the deletion process simpler.
            const [person, kafkaMessages] = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [])
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)

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
                const [personBefore, kafkaMessagesPersonBefore] = await db.createPerson(
                    TIMESTAMP,
                    {},
                    {},
                    {},
                    team.id,
                    null,
                    true,
                    uuid,
                    []
                )
                await hub.db.kafkaProducer.queueMessages(kafkaMessagesPersonBefore)
                await delayUntilEventIngested(fetchPersonsRows, 1)

                // We do an update to verify
                const [_personUpdated, updatePersonKafkaMessages] = await db.updatePerson(personBefore, {
                    properties: { foo: 'bar' },
                })
                await hub.db.kafkaProducer.queueMessages(updatePersonKafkaMessages)
                await db.kafkaProducer.flush()
                await delayUntilEventIngested(fetchPersonsRows, 2)

                const kafkaMessages = await db.deletePerson(personBefore)
                await hub.db.kafkaProducer.queueMessages(kafkaMessages)
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
            const [createdPerson, kafkaMessages] = await db.createPerson(
                TIMESTAMP,
                { foo: 'bar' },
                {},
                {},
                team.id,
                null,
                true,
                uuid,
                [{ distinctId: 'some_id' }]
            )
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)
            const person = await db.fetchPerson(team.id, 'some_id')

            expect(person).toEqual(createdPerson)
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: uuid.toString(),
                    properties: { foo: 'bar' },
                    is_identified: true,
                    created_at: TIMESTAMP,
                    version: 0,
                })
            )
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
                { prop: ISO_TIMESTAMP },
                { prop: PropertyUpdateOperation.Set }
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
                { prop: ISO_TIMESTAMP },
                { prop: PropertyUpdateOperation.Set }
            )

            expect(await db.fetchGroup(2, 0, 'group_key')).toEqual({
                id: expect.any(Number),
                team_id: 2,
                group_type_index: 0,
                group_key: 'group_key',
                group_properties: { prop: 'val' },
                created_at: TIMESTAMP,
                properties_last_updated_at: { prop: ISO_TIMESTAMP },
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
                { prop: ISO_TIMESTAMP },
                { prop: PropertyUpdateOperation.Set }
            )

            await expect(
                db.insertGroup(
                    2,
                    0,
                    'group_key',
                    { prop: 'newval' },
                    TIMESTAMP,
                    { prop: ISO_TIMESTAMP },
                    { prop: PropertyUpdateOperation.Set }
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
                { prop: ISO_TIMESTAMP },
                { prop: PropertyUpdateOperation.Set }
            )

            const originalGroup = await db.fetchGroup(2, 0, 'group_key')

            const timestamp2 = DateTime.fromISO('2000-10-14T12:42:06.502Z').toUTC()
            await db.updateGroup(
                2,
                0,
                'group_key',
                { prop: 'newVal', prop2: 2 },
                TIMESTAMP,
                { prop: timestamp2.toISO()!, prop2: timestamp2.toISO()! },
                { prop: PropertyUpdateOperation.Set, prop2: PropertyUpdateOperation.Set },
                'upsertGroup'
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

    describe('updateCohortsAndFeatureFlagsForMerge()', () => {
        let team: Team
        let sourcePersonID: BasePerson['id']
        let targetPersonID: BasePerson['id']

        async function getAllHashKeyOverrides(): Promise<any> {
            const result = await db.postgres.query(
                PostgresUse.COMMON_WRITE,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride',
                [],
                ''
            )
            return result.rows
        }

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            const [sourcePerson, kafkaMessagesSourcePerson] = await db.createPerson(
                TIMESTAMP,
                {},
                {},
                {},
                team.id,
                null,
                false,
                new UUIDT().toString(),
                [{ distinctId: 'source_person' }]
            )
            await hub.db.kafkaProducer.queueMessages(kafkaMessagesSourcePerson)
            const [targetPerson, kafkaMessagesTargetPerson] = await db.createPerson(
                TIMESTAMP,
                {},
                {},
                {},
                team.id,
                null,
                false,
                new UUIDT().toString(),
                [{ distinctId: 'target_person' }]
            )
            await hub.db.kafkaProducer.queueMessages(kafkaMessagesTargetPerson)
            sourcePersonID = sourcePerson.id
            targetPersonID = targetPerson.id
        })

        it("doesn't fail on empty data", async () => {
            await db.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)
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

            await db.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)

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

            await db.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)

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

            await db.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)

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
