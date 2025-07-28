import { DateTime } from 'luxon'

import { createTeam, insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import { Hub, InternalPerson, Team } from '../../../../types'
import { closeHub, createHub } from '../../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { parseJSON } from '../../../../utils/json-parse'
import { NoRowsUpdatedError, UUIDT } from '../../../../utils/utils'
import { PostgresPersonRepository } from './postgres-person-repository'

jest.mock('../../../../utils/logger')

describe('PostgresPersonRepository', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let repository: PostgresPersonRepository

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        repository = new PostgresPersonRepository(postgres)

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await hub.redisPool.release(redis)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    const TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

    // Helper function to create a person with all the necessary setup
    async function createTestPerson(teamId: number, distinctId: string, properties: Record<string, any> = {}) {
        const uuid = new UUIDT().toString()
        const [createdPerson, kafkaMessages] = await repository.createPerson(
            TIMESTAMP,
            properties,
            {},
            {},
            teamId,
            null,
            true,
            uuid,
            [{ distinctId }]
        )
        await hub.db.kafkaProducer.queueMessages(kafkaMessages)
        return createdPerson
    }

    describe('fetchPerson()', () => {
        it('returns undefined if person does not exist', async () => {
            const team = await getFirstTeam(hub)
            const person = await repository.fetchPerson(team.id, 'some_id')

            expect(person).toEqual(undefined)
        })

        it('returns person object if person exists', async () => {
            const team = await getFirstTeam(hub)
            const createdPerson = await createTestPerson(team.id, 'some_id', { foo: 'bar' })
            const person = await repository.fetchPerson(team.id, 'some_id')

            expect(person).toEqual(createdPerson)
            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: createdPerson.uuid,
                    properties: { foo: 'bar' },
                    is_identified: true,
                    created_at: TIMESTAMP,
                    version: 0,
                })
            )
        })

        it('throws error when both forUpdate and useReadReplica are true', async () => {
            const team = await getFirstTeam(hub)

            await expect(
                repository.fetchPerson(team.id, 'some_id', { forUpdate: true, useReadReplica: true })
            ).rejects.toThrow("can't enable both forUpdate and useReadReplica in db::fetchPerson")
        })

        it('uses read replica when useReadReplica is true', async () => {
            const team = await getFirstTeam(hub)
            const createdPerson = await createTestPerson(team.id, 'some_id', { foo: 'bar' })

            // Mock the postgres query to verify it's called with the right parameters
            const mockQuery = jest.spyOn(postgres, 'query').mockResolvedValue({
                rows: [
                    {
                        id: createdPerson.id,
                        uuid: createdPerson.uuid,
                        created_at: createdPerson.created_at.toISO(),
                        team_id: createdPerson.team_id,
                        properties: createdPerson.properties,
                        properties_last_updated_at: createdPerson.properties_last_updated_at,
                        properties_last_operation: createdPerson.properties_last_operation,
                        is_user_id: createdPerson.is_user_id,
                        version: createdPerson.version,
                        is_identified: createdPerson.is_identified,
                    },
                ],
                command: 'SELECT',
                rowCount: 1,
                oid: 0,
                fields: [],
            })

            await repository.fetchPerson(team.id, 'some_id', { useReadReplica: true })

            expect(mockQuery).toHaveBeenCalledWith(
                PostgresUse.PERSONS_READ,
                expect.stringContaining('SELECT'),
                [team.id, 'some_id'],
                'fetchPerson'
            )
        })

        it('uses write connection when useReadReplica is false', async () => {
            const team = await getFirstTeam(hub)
            const createdPerson = await createTestPerson(team.id, 'some_id', { foo: 'bar' })

            // Mock the postgres query to verify it's called with the right parameters
            const mockQuery = jest.spyOn(postgres, 'query').mockResolvedValue({
                rows: [
                    {
                        id: createdPerson.id,
                        uuid: createdPerson.uuid,
                        created_at: createdPerson.created_at.toISO(),
                        team_id: createdPerson.team_id,
                        properties: createdPerson.properties,
                        properties_last_updated_at: createdPerson.properties_last_updated_at,
                        properties_last_operation: createdPerson.properties_last_operation,
                        is_user_id: createdPerson.is_user_id,
                        version: createdPerson.version,
                        is_identified: createdPerson.is_identified,
                    },
                ],
                command: 'SELECT',
                rowCount: 1,
                oid: 0,
                fields: [],
            })

            await repository.fetchPerson(team.id, 'some_id', { useReadReplica: false })

            expect(mockQuery).toHaveBeenCalledWith(
                PostgresUse.PERSONS_WRITE,
                expect.stringContaining('SELECT'),
                [team.id, 'some_id'],
                'fetchPerson'
            )
        })

        it('adds FOR UPDATE clause when forUpdate is true', async () => {
            const team = await getFirstTeam(hub)

            // Mock the postgres query to verify the SQL contains FOR UPDATE
            const mockQuery = jest.spyOn(postgres, 'query').mockResolvedValue({
                rows: [],
                command: 'SELECT',
                rowCount: 0,
                oid: 0,
                fields: [],
            })

            await repository.fetchPerson(team.id, 'some_id', { forUpdate: true })

            expect(mockQuery).toHaveBeenCalledWith(
                PostgresUse.PERSONS_WRITE,
                expect.stringContaining('FOR UPDATE'),
                [team.id, 'some_id'],
                'fetchPerson'
            )
        })
    })

    describe('createPerson()', () => {
        it('creates a person with basic properties', async () => {
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const properties = { name: 'John Doe', email: 'john@example.com' }

            const [person, kafkaMessages] = await repository.createPerson(
                TIMESTAMP,
                properties,
                {},
                {},
                team.id,
                null,
                true,
                uuid,
                [{ distinctId: 'test-distinct-id' }]
            )

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: uuid,
                    team_id: team.id,
                    properties: properties,
                    is_identified: true,
                    created_at: TIMESTAMP,
                    version: 0,
                })
            )

            expect(kafkaMessages).toHaveLength(2) // One for person, one for distinct ID
            expect(kafkaMessages[0].topic).toBe('clickhouse_person_test')
            expect(kafkaMessages[1].topic).toBe('clickhouse_person_distinct_id_test')
        })

        it('creates a person with multiple distinct IDs', async () => {
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const properties = { name: 'Jane Doe' }

            const [person, kafkaMessages] = await repository.createPerson(
                TIMESTAMP,
                properties,
                {},
                {},
                team.id,
                null,
                false,
                uuid,
                [
                    { distinctId: 'distinct-1', version: 0 },
                    { distinctId: 'distinct-2', version: 1 },
                ]
            )

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: uuid,
                    team_id: team.id,
                    properties: properties,
                    is_identified: false,
                    created_at: TIMESTAMP,
                    version: 0,
                })
            )

            expect(kafkaMessages).toHaveLength(3) // One for person, two for distinct IDs
            expect(kafkaMessages[0].topic).toBe('clickhouse_person_test')
            expect(kafkaMessages[1].topic).toBe('clickhouse_person_distinct_id_test')
            expect(kafkaMessages[2].topic).toBe('clickhouse_person_distinct_id_test')
        })

        it('creates a person without distinct IDs', async () => {
            const team = await getFirstTeam(hub)
            const uuid = new UUIDT().toString()
            const properties = { name: 'Anonymous' }

            const [person, kafkaMessages] = await repository.createPerson(
                TIMESTAMP,
                properties,
                {},
                {},
                team.id,
                null,
                false,
                uuid
            )

            expect(person).toEqual(
                expect.objectContaining({
                    id: expect.any(String),
                    uuid: uuid,
                    team_id: team.id,
                    properties: properties,
                    is_identified: false,
                    created_at: TIMESTAMP,
                    version: 0,
                })
            )

            expect(kafkaMessages).toHaveLength(1) // Only person message, no distinct ID messages
            expect(kafkaMessages[0].topic).toBe('clickhouse_person_test')
        })

        it('throws error when trying to create a person with the same distinct ID twice', async () => {
            const team = await getFirstTeam(hub)
            const distinctId = 'duplicate-distinct-id'
            const uuid1 = new UUIDT().toString()
            const uuid2 = new UUIDT().toString()

            // Create first person successfully
            const [person1, kafkaMessages1] = await repository.createPerson(
                TIMESTAMP,
                { name: 'First Person' },
                {},
                {},
                team.id,
                null,
                true,
                uuid1,
                [{ distinctId }]
            )

            expect(person1).toBeDefined()
            expect(kafkaMessages1).toHaveLength(2)

            // Try to create second person with same distinct ID - should fail
            await expect(
                repository.createPerson(TIMESTAMP, { name: 'Second Person' }, {}, {}, team.id, null, true, uuid2, [
                    { distinctId },
                ])
            ).rejects.toThrow()

            // Verify the first person still exists and can be fetched
            const fetchedPerson = await repository.fetchPerson(team.id, distinctId)
            expect(fetchedPerson).toEqual(person1)
        })
    })

    describe('addDistinctId()', () => {
        it('should add distinct ID to person', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'existing-distinct-id', { name: 'John Doe' })
            const newDistinctId = 'new-distinct-id'
            const version = 1

            const messages = await repository.addDistinctId(person, newDistinctId, version)

            expect(messages).toHaveLength(1)
            expect(messages[0].topic).toBe('clickhouse_person_distinct_id_test')
            expect(messages[0].messages).toHaveLength(1)

            const messageValue = parseJSON(messages[0].messages[0].value as string)
            expect(messageValue).toEqual({
                person_id: person.uuid,
                team_id: team.id,
                distinct_id: 'new-distinct-id',
                version: 1,
                is_deleted: 0,
            })
        })

        it('should handle adding distinct ID with different version', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'existing-distinct-id', { name: 'John Doe' })
            const newDistinctId = 'another-distinct-id'
            const version = 5

            const messages = await repository.addDistinctId(person, newDistinctId, version)

            expect(messages).toHaveLength(1)
            expect(messages[0].topic).toBe('clickhouse_person_distinct_id_test')
            expect(messages[0].messages).toHaveLength(1)

            const messageValue = parseJSON(messages[0].messages[0].value as string)
            expect(messageValue).toEqual({
                person_id: person.uuid,
                team_id: team.id,
                distinct_id: 'another-distinct-id',
                version: 5,
                is_deleted: 0,
            })
        })
    })

    describe('deletePerson()', () => {
        it('should delete person from postgres', async () => {
            const team = await getFirstTeam(hub)
            // Create person without distinct IDs to keep deletion process simpler
            const uuid = new UUIDT().toString()
            const [person, kafkaMessages] = await repository.createPerson(
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
            await hub.db.kafkaProducer.queueMessages(kafkaMessages)

            const deleteMessages = await repository.deletePerson(person)

            // Verify person is deleted from postgres
            const fetchedPerson = await fetchPersonByPersonId(hub, team.id, person.id)
            expect(fetchedPerson).toEqual(undefined)

            // Verify kafka messages are generated
            expect(deleteMessages).toHaveLength(1)
            expect(deleteMessages[0].topic).toBe('clickhouse_person_test')
            expect(deleteMessages[0].messages).toHaveLength(1)

            const messageValue = parseJSON(deleteMessages[0].messages[0].value as string)
            expect(messageValue).toEqual({
                id: person.uuid,
                created_at: person.created_at.toFormat('yyyy-MM-dd HH:mm:ss'),
                properties: JSON.stringify(person.properties),
                team_id: person.team_id,
                is_identified: Number(person.is_identified),
                is_deleted: 1,
                version: person.version + 100, // version is incremented by 100 for deletions
            })
        })

        it('should handle deleting person that does not exist', async () => {
            const team = await getFirstTeam(hub)
            const nonExistentPerson = {
                id: '999999',
                uuid: new UUIDT().toString(),
                created_at: TIMESTAMP,
                team_id: team.id,
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                version: 0,
                is_identified: false,
            }

            const messages = await repository.deletePerson(nonExistentPerson)

            // Should return empty array when person doesn't exist
            expect(messages).toHaveLength(0)
        })
    })

    describe('moveDistinctIds()', () => {
        it('should move distinct IDs from source to target person', async () => {
            const team = await getFirstTeam(hub)
            const sourcePerson = await createTestPerson(team.id, 'source-distinct-id', { name: 'Source Person' })
            const targetPerson = await createTestPerson(team.id, 'target-distinct-id', { name: 'Target Person' })

            // Add another distinct ID to source person
            await repository.addDistinctId(sourcePerson, 'source-distinct-id-2', 1)

            const result = await repository.moveDistinctIds(sourcePerson, targetPerson)

            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.messages).toHaveLength(2) // Two distinct IDs moved

                // Verify the messages have the correct structure
                for (const message of result.messages) {
                    expect(message.topic).toBe('clickhouse_person_distinct_id_test')
                    expect(message.messages).toHaveLength(1)

                    const messageValue = parseJSON(message.messages[0].value as string)
                    expect(messageValue).toMatchObject({
                        person_id: targetPerson.uuid,
                        team_id: team.id,
                        is_deleted: 0,
                    })
                    expect(messageValue).toHaveProperty('distinct_id')
                    expect(messageValue).toHaveProperty('version')
                }
            }
        })

        it('should handle target person not found', async () => {
            const team = await getFirstTeam(hub)
            const sourcePerson = await createTestPerson(team.id, 'source-distinct-id', { name: 'Source Person' })
            const nonExistentTargetPerson = {
                id: '999999',
                uuid: new UUIDT().toString(),
                created_at: TIMESTAMP,
                team_id: team.id,
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                version: 0,
                is_identified: false,
            }

            const result = await repository.moveDistinctIds(sourcePerson, nonExistentTargetPerson)

            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error).toBe('TargetNotFound')
            }
        })

        it('should handle source person not found', async () => {
            const team = await getFirstTeam(hub)
            const targetPerson = await createTestPerson(team.id, 'target-distinct-id', { name: 'Target Person' })
            const nonExistentSourcePerson = {
                id: '888888',
                uuid: new UUIDT().toString(),
                created_at: TIMESTAMP,
                team_id: team.id,
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                version: 0,
                is_identified: false,
            }

            const result = await repository.moveDistinctIds(nonExistentSourcePerson, targetPerson)

            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error).toBe('SourceNotFound')
            }
        })
    })

    describe('addPersonlessDistinctId', () => {
        it('should insert personless distinct ID successfully', async () => {
            const team = await getFirstTeam(hub)
            const distinctId = 'test-distinct-new'

            const result = await repository.addPersonlessDistinctId(team.id, distinctId)

            expect(result).toBe(false) // is_merged should be false for new insert

            // Verify the record was actually inserted
            const selectResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team.id, distinctId],
                'verifyInsert'
            )

            expect(selectResult.rows).toHaveLength(1)
            expect(selectResult.rows[0].is_merged).toBe(false)
        })

        it('should return existing is_merged value when distinct ID already exists', async () => {
            const team = await getFirstTeam(hub)
            const distinctId = 'test-distinct-existing'

            // First insert
            const firstResult = await repository.addPersonlessDistinctId(team.id, distinctId)
            expect(firstResult).toBe(false) // is_merged should be false for new insert

            // Second insert with same distinct ID - should return existing value
            const secondResult = await repository.addPersonlessDistinctId(team.id, distinctId)
            expect(secondResult).toBe(false) // should still be false since we didn't merge it

            // Verify only one record exists
            const selectResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT COUNT(*) as count FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team.id, distinctId],
                'verifyCount'
            )

            expect(selectResult.rows[0].count).toBe('1')
        })

        it('should handle different team IDs correctly', async () => {
            const team1 = await getFirstTeam(hub)
            const team2Id = await createTeam(hub.db.postgres, team1.organization_id)
            const distinctId = 'shared-distinct-id'

            // Insert for team 1
            const result1 = await repository.addPersonlessDistinctId(team1.id, distinctId)
            expect(result1).toBe(false)

            // Insert for team 2 (should work since it's a different team)
            const result2 = await repository.addPersonlessDistinctId(team2Id, distinctId)
            expect(result2).toBe(false)

            // Verify both records exist
            const selectResult1 = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team1.id, distinctId],
                'verifyTeam1'
            )

            const selectResult2 = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team2Id, distinctId],
                'verifyTeam2'
            )

            expect(selectResult1.rows).toHaveLength(1)
            expect(selectResult2.rows).toHaveLength(1)
            expect(selectResult1.rows[0].is_merged).toBe(false)
            expect(selectResult2.rows[0].is_merged).toBe(false)
        })
    })

    describe('addPersonlessDistinctIdForMerge', () => {
        it('should insert personless distinct ID for merge successfully', async () => {
            const team = await getFirstTeam(hub)
            const distinctId = 'test-distinct-merge-new'

            const result = await repository.addPersonlessDistinctIdForMerge(team.id, distinctId)

            expect(result).toBe(true) // inserted should be true for new insert

            // Verify the record was actually inserted with is_merged = true
            const selectResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team.id, distinctId],
                'verifyMergeInsert'
            )

            expect(selectResult.rows).toHaveLength(1)
            expect(selectResult.rows[0].is_merged).toBe(true)
        })

        it('should update existing record to merged when distinct ID already exists', async () => {
            const team = await getFirstTeam(hub)
            const distinctId = 'test-distinct-merge-existing'

            // First insert as regular personless distinct ID
            const firstResult = await repository.addPersonlessDistinctId(team.id, distinctId)
            expect(firstResult).toBe(false) // is_merged should be false initially

            // Verify initial state
            let selectResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team.id, distinctId],
                'verifyInitialState'
            )
            expect(selectResult.rows[0].is_merged).toBe(false)

            // Now mark it for merge
            const mergeResult = await repository.addPersonlessDistinctIdForMerge(team.id, distinctId)
            expect(mergeResult).toBe(false) // inserted should be false since record already existed

            // Verify it was updated to merged
            selectResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team.id, distinctId],
                'verifyMergeUpdate'
            )
            expect(selectResult.rows[0].is_merged).toBe(true)
        })

        it('should handle transaction parameter correctly', async () => {
            const team = await getFirstTeam(hub)
            const distinctId = 'test-distinct-merge-transaction'

            // Use a transaction
            await postgres.transaction(PostgresUse.PERSONS_WRITE, 'test-transaction', async (tx) => {
                const result = await repository.addPersonlessDistinctIdForMerge(team.id, distinctId, tx)
                expect(result).toBe(true)

                // Verify within transaction
                const selectResult = await postgres.query(
                    tx,
                    `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                    [team.id, distinctId],
                    'verifyInTransaction'
                )
                expect(selectResult.rows).toHaveLength(1)
                expect(selectResult.rows[0].is_merged).toBe(true)
            })

            // Verify after transaction
            const selectResult = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                `SELECT is_merged FROM posthog_personlessdistinctid WHERE team_id = $1 AND distinct_id = $2`,
                [team.id, distinctId],
                'verifyAfterTransaction'
            )
            expect(selectResult.rows).toHaveLength(1)
            expect(selectResult.rows[0].is_merged).toBe(true)
        })
    })

    describe('personPropertiesSize', () => {
        it('should return properties size for existing person', async () => {
            const team = await getFirstTeam(hub)
            await createTestPerson(team.id, 'test-distinct', {
                name: 'John Doe',
                email: 'john@example.com',
                age: 30,
                preferences: {
                    theme: 'dark',
                    notifications: true,
                },
            })

            const size = await repository.personPropertiesSize(team.id, 'test-distinct')

            expect(size).toBeGreaterThan(0)
            expect(typeof size).toBe('number')
        })

        it('should return 0 for non-existent person', async () => {
            const team = await getFirstTeam(hub)
            const size = await repository.personPropertiesSize(team.id, 'non-existent-distinct')

            expect(size).toBe(0)
        })

        it('should handle different team IDs correctly', async () => {
            const team1 = await getFirstTeam(hub)
            const team2Id = await createTeam(hub.db.postgres, team1.organization_id)

            // Create person in team 1
            await createTestPerson(team1.id, 'shared-distinct', { name: 'Team 1 Person' })

            // Check size in team 1
            const size1 = await repository.personPropertiesSize(team1.id, 'shared-distinct')
            expect(size1).toBeGreaterThan(0)

            // Check size in team 2 (should be 0 since person doesn't exist there)
            const size2 = await repository.personPropertiesSize(team2Id, 'shared-distinct')
            expect(size2).toBe(0)
        })

        it('should return larger size for person with more properties', async () => {
            const team = await getFirstTeam(hub)

            // Create person with minimal properties
            await createTestPerson(team.id, 'minimal-person', { name: 'Minimal' })
            const minimalSize = await repository.personPropertiesSize(team.id, 'minimal-person')

            // Create person with extensive properties
            const extensiveProperties = {
                name: 'Extensive Person',
                email: 'extensive@example.com',
                age: 25,
                address: {
                    street: '123 Main St',
                    city: 'New York',
                    state: 'NY',
                    zip: '10001',
                    country: 'USA',
                },
                preferences: {
                    theme: 'light',
                    notifications: true,
                    privacy: {
                        shareData: false,
                        marketingEmails: true,
                    },
                },
                metadata: {
                    source: 'web',
                    campaign: 'summer2024',
                    tags: ['premium', 'active'],
                },
            }
            await createTestPerson(team.id, 'extensive-person', extensiveProperties)
            const extensiveSize = await repository.personPropertiesSize(team.id, 'extensive-person')

            expect(extensiveSize).toBeGreaterThan(minimalSize)
        })
    })

    describe('updatePerson', () => {
        it('should update person properties successfully', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John', age: 25 })

            const update = { properties: { name: 'Jane', age: 30, city: 'New York' } }
            const [updatedPerson, messages, versionDisparity] = await repository.updatePerson(person, update)

            expect(updatedPerson.properties).toEqual({ name: 'Jane', age: 30, city: 'New York' })
            expect(updatedPerson.version).toBe(person.version + 1)
            expect(messages).toHaveLength(1)
            expect(versionDisparity).toBe(false)

            // Verify the update was actually persisted
            const fetchedPerson = await repository.fetchPerson(team.id, 'test-distinct')
            expect(fetchedPerson?.properties).toEqual({ name: 'Jane', age: 30, city: 'New York' })
            expect(fetchedPerson?.version).toBe(person.version + 1)
        })

        it('should handle empty update gracefully', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            const [updatedPerson, messages, versionDisparity] = await repository.updatePerson(person, {})

            expect(updatedPerson).toEqual(person)
            expect(messages).toHaveLength(0)
            expect(versionDisparity).toBe(false)
        })

        it('should update is_identified field', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            const update = { is_identified: true }
            const [updatedPerson, messages] = await repository.updatePerson(person, update)

            expect(updatedPerson.is_identified).toBe(true)
            expect(updatedPerson.version).toBe(person.version + 1)
            expect(messages).toHaveLength(1)
        })

        it('should handle version conflicts correctly', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            // First update
            const update1 = { properties: { name: 'Jane' } }
            const [updatedPerson1, _messages1] = await repository.updatePerson(person, update1)

            // Second update with the updated person (should succeed since we're using the latest version)
            const update2 = { properties: { age: 30 } }
            const [updatedPerson2, messages2] = await repository.updatePerson(updatedPerson1, update2)

            // updatePerson replaces properties entirely, so we expect only the age property
            expect(updatedPerson2.properties).toEqual({ age: 30 })
            expect(updatedPerson2.version).toBe(updatedPerson1.version + 1)
            expect(messages2).toHaveLength(1)
        })

        it('should handle transaction parameter correctly', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            await postgres.transaction(PostgresUse.PERSONS_WRITE, 'test-transaction', async (tx) => {
                const update = { properties: { name: 'Jane' } }
                const [updatedPerson, messages] = await repository.updatePerson(person, update, 'tx', tx)

                expect(updatedPerson.properties).toEqual({ name: 'Jane' })
                expect(messages).toHaveLength(1)
            })

            // Verify after transaction commits
            const fetchedPerson = await repository.fetchPerson(team.id, 'test-distinct')
            expect(fetchedPerson?.properties).toEqual({ name: 'Jane' })
        })

        it('should handle tag parameter correctly', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            const update = { properties: { name: 'Jane' } }
            const [updatedPerson, messages] = await repository.updatePerson(person, update, 'test-tag')

            expect(updatedPerson.properties).toEqual({ name: 'Jane' })
            expect(messages).toHaveLength(1)
        })

        it('should throw NoRowsUpdatedError when person does not exist', async () => {
            const team = await getFirstTeam(hub)
            const nonExistentPerson: InternalPerson = {
                id: '1234567890',
                team_id: team.id,
                uuid: 'non-existent-uuid',
                created_at: DateTime.now(),
                properties: {},
                is_identified: false,
                version: 0,
                is_user_id: null,
                properties_last_updated_at: {},
                properties_last_operation: {},
            }

            const update = { properties: { name: 'Jane' } }
            await expect(repository.updatePerson(nonExistentPerson, update)).rejects.toThrow(NoRowsUpdatedError)
        })

        it('should handle updatePersonAssertVersion with optimistic concurrency control', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            // Create a PersonUpdate object
            const personUpdate = {
                id: person.id,
                team_id: person.team_id,
                uuid: person.uuid,
                distinct_id: 'test-distinct',
                properties: { name: 'Jane', age: 30 },
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: person.created_at,
                version: person.version,
                is_identified: person.is_identified,
                is_user_id: person.is_user_id,
                needs_write: true,
                properties_to_set: { name: 'Jane', age: 30 },
                properties_to_unset: [],
            }

            // First update should succeed
            const [actualVersion, messages] = await repository.updatePersonAssertVersion(personUpdate)

            expect(actualVersion).toBe(person.version + 1)
            expect(messages).toHaveLength(1)

            // Verify the person was actually updated
            const updatedPerson = await repository.fetchPerson(team.id, 'test-distinct')
            expect(updatedPerson?.properties).toEqual({ name: 'Jane', age: 30 })
            expect(updatedPerson?.version).toBe(person.version + 1)
        })

        it('should handle updatePersonAssertVersion with version mismatch', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct', { name: 'John' })

            // Create a PersonUpdate with an outdated version
            const personUpdate = {
                id: person.id,
                team_id: person.team_id,
                uuid: person.uuid,
                distinct_id: 'test-distinct',
                properties: { name: 'Jane', age: 30 },
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: person.created_at,
                version: person.version - 1, // Outdated version
                is_identified: person.is_identified,
                is_user_id: person.is_user_id,
                needs_write: true,
                properties_to_set: { name: 'Jane', age: 30 },
                properties_to_unset: [],
            }

            // Update should fail due to version mismatch
            const [actualVersion, messages] = await repository.updatePersonAssertVersion(personUpdate)

            expect(actualVersion).toBeUndefined()
            expect(messages).toHaveLength(0)

            // Verify the person was not updated
            const unchangedPerson = await repository.fetchPerson(team.id, 'test-distinct')
            expect(unchangedPerson?.properties).toEqual({ name: 'John' })
            expect(unchangedPerson?.version).toBe(person.version)
        })

        it('should handle updatePersonAssertVersion with non-existent person', async () => {
            const team = await getFirstTeam(hub)

            // Create a PersonUpdate for a non-existent person
            const personUpdate = {
                id: '999999',
                team_id: team.id,
                uuid: '00000000-0000-0000-0000-000000000000',
                distinct_id: 'test-distinct',
                properties: { name: 'Jane' },
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: DateTime.now(),
                version: 0,
                is_identified: false,
                is_user_id: null,
                needs_write: true,
                properties_to_set: { name: 'Jane' },
                properties_to_unset: [],
            }

            // Update should fail because person doesn't exist
            const [actualVersion, messages] = await repository.updatePersonAssertVersion(personUpdate)

            expect(actualVersion).toBeUndefined()
            expect(messages).toHaveLength(0)
        })
    })

    describe('updateCohortsAndFeatureFlagsForMerge()', () => {
        let team: Team
        let sourcePersonID: InternalPerson['id']
        let targetPersonID: InternalPerson['id']

        async function getAllHashKeyOverrides(): Promise<any> {
            const result = await hub.db.postgres.query(
                PostgresUse.COMMON_WRITE,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride',
                [],
                ''
            )
            return result.rows
        }

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            const [sourcePerson, kafkaMessagesSourcePerson] = await repository.createPerson(
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
            const [targetPerson, kafkaMessagesTargetPerson] = await repository.createPerson(
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
            await repository.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)
        })

        it('updates all valid keys when target person had no overrides', async () => {
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })

            await repository.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)

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
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: sourcePersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'existing_override_value_for_beta_feature',
            })

            await repository.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)

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
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'aloha',
                hash_key: 'override_value_for_aloha',
            })
            await insertRow(hub.db.postgres, 'posthog_featureflaghashkeyoverride', {
                team_id: team.id,
                person_id: targetPersonID,
                feature_flag_key: 'beta-feature',
                hash_key: 'override_value_for_beta_feature',
            })

            await repository.updateCohortsAndFeatureFlagsForMerge(team.id, sourcePersonID, targetPersonID)

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

    describe('properties size logging feature flag', () => {
        it('should have identical output whether properties size logging is enabled or disabled', async () => {
            const team = await getFirstTeam(hub)

            const person1 = await createTestPerson(team.id, 'test-distinct-1', {
                name: 'John',
                age: 25,
                email: 'john@example.com',
                largeProperty: 'x'.repeat(1000),
            })
            const person2 = await createTestPerson(team.id, 'test-distinct-2', {
                name: 'John',
                age: 25,
                email: 'john@example.com',
                largeProperty: 'x'.repeat(1000),
            })

            const repositoryWithLogging = new PostgresPersonRepository(postgres, {
                propertiesSizeLoggingPercentage: 100,
            })
            const repositoryWithoutLogging = new PostgresPersonRepository(postgres, {
                propertiesSizeLoggingPercentage: 0,
            })

            const update = {
                properties: {
                    name: 'Jane',
                    age: 30,
                    city: 'New York',
                    anotherLargeProperty: 'y'.repeat(1500),
                },
            }

            const [updatedPerson1, messages1, versionDisparity1] = await repositoryWithLogging.updatePerson(
                person1,
                update,
                'test-with-logging'
            )
            const [updatedPerson2, messages2, versionDisparity2] = await repositoryWithoutLogging.updatePerson(
                person2,
                update,
                'test-without-logging'
            )

            expect(updatedPerson1.properties).toEqual(updatedPerson2.properties)
            expect(updatedPerson1.is_identified).toEqual(updatedPerson2.is_identified)
            expect(updatedPerson1.version).toEqual(updatedPerson2.version)
            expect(versionDisparity1).toEqual(versionDisparity2)
            expect(messages1).toHaveLength(messages2.length)

            const fetchedPerson1 = await repositoryWithLogging.fetchPerson(team.id, 'test-distinct-1')
            const fetchedPerson2 = await repositoryWithoutLogging.fetchPerson(team.id, 'test-distinct-2')

            expect(fetchedPerson1?.properties).toEqual(fetchedPerson2?.properties)
            expect(fetchedPerson1?.version).toEqual(fetchedPerson2?.version)
        })

        it('should have identical behavior for updatePersonAssertVersion regardless of logging configuration', async () => {
            const team = await getFirstTeam(hub)

            const person1 = await createTestPerson(team.id, 'test-assert-1', { name: 'John', data: 'x'.repeat(2000) })
            const person2 = await createTestPerson(team.id, 'test-assert-2', { name: 'John', data: 'x'.repeat(2000) })

            const repositoryWithLogging = new PostgresPersonRepository(postgres, {
                propertiesSizeLoggingPercentage: 100,
            })
            const repositoryWithoutLogging = new PostgresPersonRepository(postgres, {
                propertiesSizeLoggingPercentage: 0,
            })

            const createPersonUpdate = (person: InternalPerson, distinctId: string) => ({
                id: person.id,
                team_id: person.team_id,
                uuid: person.uuid,
                distinct_id: distinctId,
                properties: { name: 'Jane', age: 30, data: 'y'.repeat(2500) },
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: person.created_at,
                version: person.version,
                is_identified: person.is_identified,
                is_user_id: person.is_user_id,
                needs_write: true,
                properties_to_set: { name: 'Jane', age: 30, data: 'y'.repeat(2500) },
                properties_to_unset: [],
            })

            const personUpdate1 = createPersonUpdate(person1, 'test-assert-1')
            const personUpdate2 = createPersonUpdate(person2, 'test-assert-2')

            const [actualVersion1, messages1] = await repositoryWithLogging.updatePersonAssertVersion(personUpdate1)
            const [actualVersion2, messages2] = await repositoryWithoutLogging.updatePersonAssertVersion(personUpdate2)

            expect(actualVersion1).toBeDefined()
            expect(actualVersion2).toBeDefined()
            expect(actualVersion1).toEqual(person1.version + 1)
            expect(actualVersion2).toEqual(person2.version + 1)
            expect(messages1).toHaveLength(messages2.length)

            const fetchedPerson1 = await repositoryWithLogging.fetchPerson(team.id, 'test-assert-1')
            const fetchedPerson2 = await repositoryWithoutLogging.fetchPerson(team.id, 'test-assert-2')

            expect(fetchedPerson1?.properties).toEqual(fetchedPerson2?.properties)
            expect(fetchedPerson1?.version).toEqual(fetchedPerson2?.version)
        })

        it('should work with default options (no logging)', async () => {
            const team = await getFirstTeam(hub)
            const defaultRepository = new PostgresPersonRepository(postgres)

            const person = await createTestPerson(team.id, 'test-default', { name: 'John' })
            const update = { properties: { name: 'Jane', city: 'Boston' } }

            const [updatedPerson, messages, versionDisparity] = await defaultRepository.updatePerson(person, update)

            expect(updatedPerson.properties).toEqual({ name: 'Jane', city: 'Boston' })
            expect(updatedPerson.version).toBe(person.version + 1)
            expect(messages).toHaveLength(1)
            expect(versionDisparity).toBe(false)
        })
    })
})

// Helper function from the original test file
async function getFirstTeam(hub: Hub): Promise<Team> {
    const teams = await hub.db.postgres.query(
        PostgresUse.COMMON_WRITE,
        'SELECT * FROM posthog_team LIMIT 1',
        [],
        'getFirstTeam'
    )
    return teams.rows[0]
}

async function fetchPersonByPersonId(hub: Hub, teamId: number, personId: string): Promise<any | undefined> {
    const selectResult = await hub.db.postgres.query(
        PostgresUse.PERSONS_WRITE,
        `SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2`,
        [teamId, personId],
        'fetchPersonByPersonId'
    )

    return selectResult.rows[0]
}
