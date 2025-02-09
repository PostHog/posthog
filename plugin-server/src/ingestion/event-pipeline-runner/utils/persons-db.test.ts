import { DateTime } from 'luxon'
import { Pool } from 'pg'

import { delayUntilEventIngested, resetTestDatabaseClickhouse } from '../../../_tests/helpers/clickhouse'
import { createOrganization, createTeam, getFirstTeam, insertRow, resetTestDatabase } from '../../../_tests/helpers/sql'
import { defaultConfig } from '../../../config/config'
import { Hub, Person, PropertyUpdateOperation, Team } from '../../../types'
import { DependencyUnavailableError } from '../../../utils/errors'
import { closeHub, createHub } from '../../../utils/hub'
import { PostgresRouter, PostgresUse } from '../../../utils/postgres'
import { RaceConditionError, UUIDT } from '../../../utils/utils'
import { PersonsDB } from './persons-db'
import { generateKafkaPersonUpdateMessage } from './utils'

jest.mock('../../../utils/status')

describe('DB', () => {
    let hub: Hub
    let db: PersonsDB

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {})
        db = new PersonsDB(hub.postgres, hub.kafkaProducer)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()

    async function fetchPersonByPersonId(teamId: number, personId: number): Promise<Person | undefined> {
        const selectResult = await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
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

        const result = await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
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
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, false, uuid, [{ distinctId }])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)

            expect(fetched_person!.is_identified).toEqual(false)
            expect(fetched_person!.properties).toEqual({})
            expect(fetched_person!.properties_last_operation).toEqual({})
            expect(fetched_person!.properties_last_updated_at).toEqual({})
            expect(fetched_person!.uuid).toEqual(uuid)
            expect(fetched_person!.team_id).toEqual(team.id)
        })

        test('without properties indentified true', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [{ distinctId }])
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
                [{ distinctId }]
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
            jest.spyOn(db.kafkaProducer!, 'queueMessages')
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const distinctId = 'distinct_id1'
            // Note that we update the person badly in case of concurrent updates, but lets make sure we're consistent
            const personDbBefore = await db.createPerson(TIMESTAMP, { c: 'aaa' }, {}, {}, team.id, null, false, uuid, [
                { distinctId },
            ])
            const providedPersonTs = DateTime.fromISO('2000-04-04T11:42:06.502Z').toUTC()
            const personProvided = { ...personDbBefore, properties: { c: 'bbb' }, created_at: providedPersonTs }
            const updateTs = DateTime.fromISO('2000-04-04T11:42:06.502Z').toUTC()
            const update = { created_at: updateTs }
            const [updatedPerson, kafkaMessages] = await db.updatePersonDeprecated(personProvided, update)
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
                const [_p, updatePersonKafkaMessages] = await db.updatePersonDeprecated(person, {
                    properties: { foo: 'bar' },
                })
                await hub.db.kafkaProducer.queueMessages(updatePersonKafkaMessages)
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
                { distinctId: 'some_id' },
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
                { prop: TIMESTAMP.toISO()! },
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

    describe('updateCohortsAndFeatureFlagsForMerge()', () => {
        let team: Team
        let sourcePersonID: Person['id']
        let targetPersonID: Person['id']

        async function getAllHashKeyOverrides(): Promise<any> {
            const result = await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
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
                [{ distinctId: 'source_person' }]
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
                [{ distinctId: 'target_person' }]
            )
            sourcePersonID = sourcePerson.id
            targetPersonID = targetPerson.id
        })

        it("doesn't fail on empty data", async () => {
            await db.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)
        })

        it('updates all valid keys when target person had no overrides', async () => {
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
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
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
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
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(hub.postgres, 'posthog_featureflaghashkeyoverride', {
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
})

describe('PostgresRouter()', () => {
    test('throws DependencyUnavailableError on postgres errors', async () => {
        const errorMessage =
            'connection to server at "posthog-pgbouncer" (171.20.65.128), port 6543 failed: server closed the connection unexpectedly'
        const pgQueryMock = jest.spyOn(Pool.prototype, 'query').mockImplementation(() => {
            return Promise.reject(new Error(errorMessage))
        })

        const router = new PostgresRouter(defaultConfig, null)
        await expect(router.query(PostgresUse.COMMON_WRITE, 'SELECT 1;', null, 'testing')).rejects.toEqual(
            new DependencyUnavailableError(errorMessage, 'Postgres', new Error(errorMessage))
        )
        pgQueryMock.mockRestore()
    })
})
