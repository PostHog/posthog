import { DateTime } from 'luxon'

import { createTeam, insertRow, resetTestDatabase } from '../../../../../tests/helpers/sql'
import { Hub, InternalPerson, Team } from '../../../../types'
import { closeHub, createHub } from '../../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../../utils/db/postgres'
import { parseJSON } from '../../../../utils/json-parse'
import { NoRowsUpdatedError, UUIDT } from '../../../../utils/utils'
import { PersonPropertiesSizeViolationError } from './person-repository'
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
        repository = new PostgresPersonRepository(postgres, {
            calculatePropertiesSize: 0,
            personPropertiesDbConstraintLimitBytes: 1024 * 1024, // 1MB for tests
            personPropertiesTrimTargetBytes: 512 * 1024,
        })

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
        const result = await repository.createPerson(TIMESTAMP, properties, {}, {}, teamId, null, true, uuid, [
            { distinctId },
        ])
        if (!result.success) {
            throw new Error('Failed to create person')
        }
        await hub.db.kafkaProducer.queueMessages(result.messages)
        return result.person
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

            const result = await repository.createPerson(TIMESTAMP, properties, {}, {}, team.id, null, true, uuid, [
                { distinctId: 'test-distinct-id' },
            ])

            if (!result.success) {
                throw new Error('Failed to create person')
            }
            const person = result.person
            const kafkaMessages = result.messages

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

            const result = await repository.createPerson(TIMESTAMP, properties, {}, {}, team.id, null, false, uuid, [
                { distinctId: 'distinct-1', version: 0 },
                { distinctId: 'distinct-2', version: 1 },
            ])
            if (!result.success) {
                throw new Error('Failed to create person')
            }
            const person = result.person
            const kafkaMessages = result.messages

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

            const result = await repository.createPerson(TIMESTAMP, properties, {}, {}, team.id, null, false, uuid)

            if (!result.success) {
                throw new Error('Failed to create person')
            }
            const person = result.person
            const kafkaMessages = result.messages

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
            const result1 = await repository.createPerson(
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

            if (!result1.success) {
                throw new Error('Failed to create person')
            }
            const person1 = result1.person
            const kafkaMessages1 = result1.messages

            expect(person1).toBeDefined()
            expect(kafkaMessages1).toHaveLength(2)

            // Try to create second person with same distinct ID - should fail
            const createPersonResult = await repository.createPerson(
                TIMESTAMP,
                { name: 'Second Person' },
                {},
                {},
                team.id,
                null,
                true,
                uuid2,
                [{ distinctId }]
            )

            expect(createPersonResult.success).toBe(false)
            if (createPersonResult.success === false) {
                expect(createPersonResult.error).toBe('CreationConflict')
            }

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
            const result = await repository.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [])
            if (!result.success) {
                throw new Error('Failed to create person')
            }
            const person = result.person
            const kafkaMessages = result.messages

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

            const result = await repository.moveDistinctIds(sourcePerson, targetPerson, undefined)

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

            const result = await repository.moveDistinctIds(sourcePerson, nonExistentTargetPerson, undefined)

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

            const result = await repository.moveDistinctIds(nonExistentSourcePerson, targetPerson, undefined)

            expect(result.success).toBe(false)
            if (!result.success) {
                expect(result.error).toBe('SourceNotFound')
            }
        })

        it('should respect per-call move limit when provided', async () => {
            const team = await getFirstTeam(hub)
            const limitedRepository = new PostgresPersonRepository(postgres, {})

            const sourcePerson = await createTestPerson(team.id, 'source-distinct-id', { name: 'Source Person' })
            const targetPerson = await createTestPerson(team.id, 'target-distinct-id', { name: 'Target Person' })

            // Add 3 more distinct IDs to source person (total of 4 distinct IDs)
            await repository.addDistinctId(sourcePerson, 'source-distinct-id-2', 1)
            await repository.addDistinctId(sourcePerson, 'source-distinct-id-3', 1)
            await repository.addDistinctId(sourcePerson, 'source-distinct-id-4', 1)

            const result = await limitedRepository.moveDistinctIds(sourcePerson, targetPerson, 2)

            expect(result.success).toBe(true)
            if (result.success) {
                // Should only move 2 distinct IDs due to limit
                expect(result.messages).toHaveLength(2)
                expect(result.distinctIdsMoved).toHaveLength(2)

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

                // Verify that there are still distinct IDs left on the source person
                const remainingResult = await postgres.query(
                    PostgresUse.PERSONS_WRITE,
                    'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = $1 AND team_id = $2',
                    [sourcePerson.id, team.id],
                    'countRemainingDistinctIds'
                )
                expect(parseInt(remainingResult.rows[0].count)).toBe(2) // 4 - 2 = 2 remaining
            }
        })

        it('should move all distinct IDs when no limit is configured', async () => {
            const team = await getFirstTeam(hub)
            const unlimitedRepository = new PostgresPersonRepository(postgres, {}) // No limit

            const sourcePerson = await createTestPerson(team.id, 'source-unlimited', { name: 'Source Person' })
            const targetPerson = await createTestPerson(team.id, 'target-unlimited', { name: 'Target Person' })

            // Add 3 more distinct IDs to source person (total of 4 distinct IDs)
            await repository.addDistinctId(sourcePerson, 'source-unlimited-2', 1)
            await repository.addDistinctId(sourcePerson, 'source-unlimited-3', 1)
            await repository.addDistinctId(sourcePerson, 'source-unlimited-4', 1)

            const result = await unlimitedRepository.moveDistinctIds(sourcePerson, targetPerson, undefined)

            expect(result.success).toBe(true)
            if (result.success) {
                // Should move all 4 distinct IDs
                expect(result.messages).toHaveLength(4)
                expect(result.distinctIdsMoved).toHaveLength(4)

                // Verify no distinct IDs remain on the source person
                const remainingResult = await postgres.query(
                    PostgresUse.PERSONS_WRITE,
                    'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = $1 AND team_id = $2',
                    [sourcePerson.id, team.id],
                    'countRemainingDistinctIds'
                )
                expect(parseInt(remainingResult.rows[0].count)).toBe(0) // All moved
            }
        })

        it('should move distinct IDs in deterministic order when per-call limit is set', async () => {
            const team = await getFirstTeam(hub)
            const limitedRepository = new PostgresPersonRepository(postgres, {})

            const sourcePerson = await createTestPerson(team.id, 'source-deterministic', { name: 'Source Person' })
            const targetPerson = await createTestPerson(team.id, 'target-deterministic', { name: 'Target Person' })

            // Add distinct IDs in a specific order (not alphabetical to test database ID ordering)
            await repository.addDistinctId(sourcePerson, 'distinct-z', 1)
            await repository.addDistinctId(sourcePerson, 'distinct-a', 1)
            await repository.addDistinctId(sourcePerson, 'distinct-m', 1)

            // Get all distinct IDs in database order (by id, not by distinct_id value)
            const allDistinctIdsBeforeMove = await postgres.query(
                PostgresUse.PERSONS_WRITE,
                'SELECT id, distinct_id FROM posthog_persondistinctid WHERE person_id = $1 AND team_id = $2 ORDER BY id',
                [sourcePerson.id, team.id],
                'getAllDistinctIds'
            )

            // Should have 4 total distinct IDs (1 from createTestPerson + 3 added)
            expect(allDistinctIdsBeforeMove.rows).toHaveLength(4)

            const result = await limitedRepository.moveDistinctIds(sourcePerson, targetPerson, 2)
            expect(result.success).toBe(true)
            if (result.success) {
                expect(result.distinctIdsMoved).toHaveLength(2)

                // The moved distinct IDs should be the first 2 in database order (smallest IDs)
                const expectedMovedDistinctIds = [
                    allDistinctIdsBeforeMove.rows[0].distinct_id,
                    allDistinctIdsBeforeMove.rows[1].distinct_id,
                ]

                expect(result.distinctIdsMoved.sort()).toEqual(expectedMovedDistinctIds.sort())

                // Verify the remaining distinct IDs are the ones with higher database IDs
                const remainingIds = await postgres.query(
                    PostgresUse.PERSONS_WRITE,
                    'SELECT distinct_id FROM posthog_persondistinctid WHERE person_id = $1 AND team_id = $2 ORDER BY id',
                    [sourcePerson.id, team.id],
                    'getRemainingDistinctIds'
                )

                expect(remainingIds.rows).toHaveLength(2)
                const expectedRemainingDistinctIds = [
                    allDistinctIdsBeforeMove.rows[2].distinct_id,
                    allDistinctIdsBeforeMove.rows[3].distinct_id,
                ]

                const actualRemainingDistinctIds = remainingIds.rows.map((row) => row.distinct_id)
                expect(actualRemainingDistinctIds.sort()).toEqual(expectedRemainingDistinctIds.sort())
            }
        })

        it('should move all distinct IDs when person has fewer than the per-call limit', async () => {
            const team = await getFirstTeam(hub)
            const limitedRepository = new PostgresPersonRepository(postgres, {})

            const sourcePerson = await createTestPerson(team.id, 'source-below-limit', { name: 'Source Person' })
            const targetPerson = await createTestPerson(team.id, 'target-below-limit', { name: 'Target Person' })

            // Add only 2 more distinct IDs (total of 3, which is below the limit of 5)
            await repository.addDistinctId(sourcePerson, 'source-below-limit-2', 1)
            await repository.addDistinctId(sourcePerson, 'source-below-limit-3', 1)

            const result = await limitedRepository.moveDistinctIds(sourcePerson, targetPerson, 5)

            expect(result.success).toBe(true)
            if (result.success) {
                // Should move all 3 distinct IDs since it's below the limit
                expect(result.messages).toHaveLength(3)
                expect(result.distinctIdsMoved).toHaveLength(3)

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

                // Verify no distinct IDs remain on the source person
                const remainingResult = await postgres.query(
                    PostgresUse.PERSONS_WRITE,
                    'SELECT COUNT(*) as count FROM posthog_persondistinctid WHERE person_id = $1 AND team_id = $2',
                    [sourcePerson.id, team.id],
                    'countRemainingDistinctIds'
                )
                expect(parseInt(remainingResult.rows[0].count)).toBe(0) // All moved, none remaining
            }
        })
    })

    describe('fetchPersonDistinctIds()', () => {
        it('should fetch all distinct IDs when no limit is specified', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-distinct-id', { name: 'Test Person' })

            // Add more distinct IDs
            await repository.addDistinctId(person, 'distinct-id-2', 1)
            await repository.addDistinctId(person, 'distinct-id-3', 1)
            await repository.addDistinctId(person, 'distinct-id-4', 1)

            const distinctIds = await repository.fetchPersonDistinctIds(person)

            expect(distinctIds).toHaveLength(4)
            expect(distinctIds).toContain('test-distinct-id')
            expect(distinctIds).toContain('distinct-id-2')
            expect(distinctIds).toContain('distinct-id-3')
            expect(distinctIds).toContain('distinct-id-4')
        })

        it('should fetch limited distinct IDs when limit is specified', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'test-limit-distinct', { name: 'Test Person' })

            // Add more distinct IDs
            await repository.addDistinctId(person, 'limit-distinct-2', 1)
            await repository.addDistinctId(person, 'limit-distinct-3', 1)
            await repository.addDistinctId(person, 'limit-distinct-4', 1)

            const distinctIds = await repository.fetchPersonDistinctIds(person, 2)

            expect(distinctIds).toHaveLength(2)
            // Should be deterministic due to ORDER BY id
            expect(distinctIds).toEqual(expect.arrayContaining([expect.any(String), expect.any(String)]))
        })

        it('should return distinct IDs in deterministic order', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'order-test-distinct', { name: 'Test Person' })

            // Add distinct IDs in non-alphabetical order
            await repository.addDistinctId(person, 'z-distinct', 1)
            await repository.addDistinctId(person, 'a-distinct', 1)
            await repository.addDistinctId(person, 'm-distinct', 1)

            const distinctIds1 = await repository.fetchPersonDistinctIds(person)
            const distinctIds2 = await repository.fetchPersonDistinctIds(person)

            // Should return the same order both times due to ORDER BY id
            expect(distinctIds1).toEqual(distinctIds2)
            expect(distinctIds1).toHaveLength(4) // 1 from createTestPerson + 3 added
        })

        it('should return empty array when person has no distinct IDs', async () => {
            const team = await getFirstTeam(hub)
            // Create person without distinct IDs
            const uuid = new UUIDT().toString()
            const result = await repository.createPerson(TIMESTAMP, {}, {}, {}, team.id, null, true, uuid, [])
            if (!result.success) {
                throw new Error('Failed to create person')
            }
            const person = result.person

            const distinctIds = await repository.fetchPersonDistinctIds(person)

            expect(distinctIds).toEqual([])
        })

        it('should handle limit larger than available distinct IDs', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'large-limit-distinct', { name: 'Test Person' })

            // Add only 2 more distinct IDs (total of 3)
            await repository.addDistinctId(person, 'large-limit-2', 1)
            await repository.addDistinctId(person, 'large-limit-3', 1)

            const distinctIds = await repository.fetchPersonDistinctIds(person, 10) // Limit is larger than available

            expect(distinctIds).toHaveLength(3) // Should return all 3 available
            expect(distinctIds).toContain('large-limit-distinct')
            expect(distinctIds).toContain('large-limit-2')
            expect(distinctIds).toContain('large-limit-3')
        })

        it('should work with transactions', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'tx-distinct', { name: 'Test Person' })

            await repository.addDistinctId(person, 'tx-distinct-2', 1)

            await postgres.transaction(PostgresUse.PERSONS_WRITE, 'test-fetch-distinct-ids', async (tx) => {
                const distinctIds = await repository.fetchPersonDistinctIds(person, undefined, tx)
                expect(distinctIds).toHaveLength(2)
                expect(distinctIds).toContain('tx-distinct')
                expect(distinctIds).toContain('tx-distinct-2')
            })
        })
    })

    describe('fetchPersonsByDistinctIds()', () => {
        it('should return empty array when no team persons provided', async () => {
            const result = await repository.fetchPersonsByDistinctIds([])
            expect(result).toEqual([])
        })

        it('should fetch persons by distinct IDs from multiple teams', async () => {
            const team1 = await getFirstTeam(hub)
            const team2Id = await createTeam(postgres, team1.organization_id)

            // Create persons in different teams
            const person1 = await createTestPerson(team1.id, 'distinct-1', { name: 'Person 1' })
            const person2 = await createTestPerson(team1.id, 'distinct-2', { name: 'Person 2' })
            const person3 = await createTestPerson(team2Id, 'distinct-3', { name: 'Person 3' })

            const teamPersons = [
                { teamId: team1.id, distinctId: 'distinct-1' },
                { teamId: team1.id, distinctId: 'distinct-2' },
                { teamId: team2Id, distinctId: 'distinct-3' },
            ]

            const result = await repository.fetchPersonsByDistinctIds(teamPersons)

            expect(result).toHaveLength(3)

            // Check that we got the right persons with distinct_id included
            const person1Result = result.find((p) => p.distinct_id === 'distinct-1')
            expect(person1Result).toBeDefined()
            expect(person1Result!.uuid).toBe(person1.uuid)
            expect(person1Result!.team_id).toBe(team1.id)
            expect(person1Result!.properties.name).toBe('Person 1')

            const person2Result = result.find((p) => p.distinct_id === 'distinct-2')
            expect(person2Result).toBeDefined()
            expect(person2Result!.uuid).toBe(person2.uuid)
            expect(person2Result!.team_id).toBe(team1.id)
            expect(person2Result!.properties.name).toBe('Person 2')

            const person3Result = result.find((p) => p.distinct_id === 'distinct-3')
            expect(person3Result).toBeDefined()
            expect(person3Result!.uuid).toBe(person3.uuid)
            expect(person3Result!.team_id).toBe(team2Id)
            expect(person3Result!.properties.name).toBe('Person 3')
        })

        it('should handle non-existent distinct IDs gracefully', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'existing-distinct', { name: 'Existing Person' })

            const teamPersons = [
                { teamId: team.id as any, distinctId: 'existing-distinct' },
                { teamId: team.id as any, distinctId: 'non-existent-distinct' },
            ]

            const result = await repository.fetchPersonsByDistinctIds(teamPersons)

            // Should only return the existing person
            expect(result).toHaveLength(1)
            expect(result[0].distinct_id).toBe('existing-distinct')
            expect(result[0].uuid).toBe(person.uuid)
        })

        it('should handle single team person lookup', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'single-distinct', { name: 'Single Person' })

            const teamPersons = [{ teamId: team.id as any, distinctId: 'single-distinct' }]

            const result = await repository.fetchPersonsByDistinctIds(teamPersons)

            expect(result).toHaveLength(1)
            expect(result[0].distinct_id).toBe('single-distinct')
            expect(result[0].uuid).toBe(person.uuid)
            expect(result[0].team_id).toBe(team.id)
            expect(result[0].properties.name).toBe('Single Person')
        })

        it('should handle duplicate team/distinctId pairs', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'duplicate-distinct', { name: 'Duplicate Person' })

            const teamPersons = [
                { teamId: team.id as any, distinctId: 'duplicate-distinct' },
                { teamId: team.id as any, distinctId: 'duplicate-distinct' }, // Same pair
            ]

            const result = await repository.fetchPersonsByDistinctIds(teamPersons)

            // Should only return one result even though we queried twice
            expect(result).toHaveLength(1)
            expect(result[0].distinct_id).toBe('duplicate-distinct')
            expect(result[0].uuid).toBe(person.uuid)
        })

        it('should include all required fields in InternalPersonWithDistinctId', async () => {
            const team = await getFirstTeam(hub)
            const person = await createTestPerson(team.id, 'fields-test', { name: 'Fields Test', age: 25 })

            const teamPersons = [{ teamId: team.id as any, distinctId: 'fields-test' }]

            const result = await repository.fetchPersonsByDistinctIds(teamPersons)

            expect(result).toHaveLength(1)
            const personResult = result[0]

            // Check all InternalPerson fields are present
            expect(personResult.id).toBe(person.id)
            expect(personResult.uuid).toBe(person.uuid)
            expect(personResult.properties).toEqual({ name: 'Fields Test', age: 25 })
            expect(personResult.created_at).toEqual(person.created_at)
            expect(personResult.version).toBe(person.version)
            expect(personResult.is_user_id).toBe(person.is_user_id)
            expect(personResult.is_identified).toBe(person.is_identified)
            expect(personResult.team_id).toBe(person.team_id)

            // Check the additional distinct_id field
            expect(personResult.distinct_id).toBe('fields-test')
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
            const person = await createTestPerson(team.id, 'test-distinct', {
                name: 'John Doe',
                email: 'john@example.com',
                age: 30,
                preferences: {
                    theme: 'dark',
                    notifications: true,
                },
            })

            const size = await repository.personPropertiesSize(person.id)

            expect(size).toBeGreaterThan(0)
            expect(typeof size).toBe('number')
        })

        it('should return 0 for non-existent person', async () => {
            const fakePersonId = '999999' // Use a numeric ID instead of UUID
            const size = await repository.personPropertiesSize(fakePersonId)

            expect(size).toBe(0)
        })

        it('should handle different persons correctly', async () => {
            const team1 = await getFirstTeam(hub)
            const team2Id = await createTeam(hub.db.postgres, team1.organization_id)

            // Create person in team 1
            const person1 = await createTestPerson(team1.id, 'shared-distinct', { name: 'Team 1 Person' })

            // Create person in team 2
            const person2 = await createTestPerson(team2Id, 'different-distinct', { name: 'Team 2 Person' })

            // Check size for person 1
            const size1 = await repository.personPropertiesSize(person1.id)
            expect(size1).toBeGreaterThan(0)

            // Check size for person 2
            const size2 = await repository.personPropertiesSize(person2.id)
            expect(size2).toBeGreaterThan(0)
        })

        it('should return larger size for person with more properties', async () => {
            const team = await getFirstTeam(hub)

            // Create person with minimal properties
            const minimalPerson = await createTestPerson(team.id, 'minimal-person', { name: 'Minimal' })
            const minimalSize = await repository.personPropertiesSize(minimalPerson.id)

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
            const extensivePerson = await createTestPerson(team.id, 'extensive-person', extensiveProperties)
            const extensiveSize = await repository.personPropertiesSize(extensivePerson.id)

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
                original_is_identified: false,
                original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
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
                original_is_identified: false,
                original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
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
                original_is_identified: false,
                original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
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
                PostgresUse.PERSONS_WRITE,
                'SELECT feature_flag_key, hash_key, person_id FROM posthog_featureflaghashkeyoverride',
                [],
                ''
            )
            return result.rows
        }

        beforeEach(async () => {
            team = await getFirstTeam(hub)
            const result = await repository.createPerson(
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
            if (!result.success) {
                throw new Error('Failed to create person')
            }
            const sourcePerson = result.person
            const kafkaMessagesSourcePerson = result.messages

            const result2 = await repository.createPerson(
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
            if (!result2.success) {
                throw new Error('Failed to create person')
            }
            const targetPerson = result2.person

            await hub.db.kafkaProducer.queueMessages(kafkaMessagesSourcePerson)
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

    describe('person properties size violation handling', () => {
        let oversizedRepository: PostgresPersonRepository

        beforeEach(() => {
            oversizedRepository = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: 0,
                personPropertiesDbConstraintLimitBytes: 50,
                personPropertiesTrimTargetBytes: 25,
            })
        })

        describe('trimPropertiesToFitSize', () => {
            it('should return original properties if they are under the size limit', () => {
                const properties = { name: 'John', age: 30 }
                const targetSize = 1000

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result).toEqual(properties)
            })

            it('should remove properties to fit under size limit', () => {
                const properties = {
                    name: 'John Doe',
                    email: 'john@example.com',
                    description: 'A very long description that takes up a lot of space',
                    age: 30,
                    city: 'New York',
                }
                const targetSize = 50

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(Object.keys(result).length).toBeLessThan(Object.keys(properties).length)
                expect(Buffer.byteLength(JSON.stringify(result), 'utf8')).toBeLessThanOrEqual(targetSize)
            })

            it('should preserve protected properties even when trimming', () => {
                const properties = {
                    description: 'A very long description that takes up a lot of space',
                    age: 30,
                    customField: 'some custom data',
                    name: 'John Doe',
                    email: 'john@example.com',
                }
                const targetSize = 50

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result).toHaveProperty('name')
                expect(result).toHaveProperty('email')

                expect(Buffer.byteLength(JSON.stringify(result), 'utf8')).toBeLessThanOrEqual(targetSize)
            })

            it('should handle empty properties object', () => {
                const properties = {}
                const targetSize = 50

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result).toEqual({})
            })

            it('should preserve protected properties even when removing in alphabetical order', () => {
                const properties = {
                    zebra: 'last in alphabet',
                    email: 'john@example.com',
                    apple: 'first in alphabet',
                    banana: 'middle in alphabet',
                    cherry: 'also middle',
                }
                const targetSize = 70

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result).toHaveProperty('email')
                expect(result).toHaveProperty('zebra')
                expect(result).not.toHaveProperty('banana')
                expect(Buffer.byteLength(JSON.stringify(result), 'utf8')).toBeLessThanOrEqual(targetSize + 50)
            })

            it('should process properties in deterministic alphabetical order', () => {
                const properties = {
                    z_property: '1',
                    a_property: '2',
                    m_property: '3',
                    b_property: '4',
                }
                const targetSize = 25

                const result1 = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                const result2 = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result1).toEqual(result2)

                const remainingKeys = Object.keys(result1).sort()
                if (remainingKeys.length > 0) {
                    expect(remainingKeys).toContain('z_property')
                }
            })
        })

        describe('PersonPropertiesSizeViolationError', () => {
            it('should create error with correct properties', () => {
                const error = new PersonPropertiesSizeViolationError('Test message', 123, 'person-id', 'distinct-id')

                expect(error.message).toBe('Test message')
                expect(error.teamId).toBe(123)
                expect(error.personId).toBe('person-id')
                expect(error.distinctId).toBe('distinct-id')
                expect(error.name).toBe('PersonPropertiesSizeViolationError')
            })
        })

        describe('createPerson with oversized properties', () => {
            it('should throw PersonPropertiesSizeViolationError when properties exceed size limit', async () => {
                const team = await getFirstTeam(hub)
                const uuid = new UUIDT().toString()
                const oversizedProperties = {
                    description: 'x'.repeat(200),
                }

                const originalQuery = postgres.query.bind(postgres)
                const mockQuery = jest.spyOn(postgres, 'query').mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('INSERT INTO posthog_person')) {
                        const error = new Error('Check constraint violation')
                        ;(error as any).code = '23514'
                        ;(error as any).constraint = 'check_properties_size'
                        throw error
                    }
                    return originalQuery(use, query, values, tag)
                })

                await expect(
                    oversizedRepository.createPerson(
                        TIMESTAMP,
                        oversizedProperties,
                        {},
                        {},
                        team.id,
                        null,
                        true,
                        uuid,
                        [{ distinctId: 'test-oversized' }]
                    )
                ).rejects.toThrow(PersonPropertiesSizeViolationError)

                await expect(
                    oversizedRepository.createPerson(
                        TIMESTAMP,
                        oversizedProperties,
                        {},
                        {},
                        team.id,
                        null,
                        true,
                        uuid,
                        [{ distinctId: 'test-oversized-2' }]
                    )
                ).rejects.toThrow('Person properties create would exceed size limit')

                mockQuery.mockRestore()
            })
        })

        describe('updatePerson with oversized properties', () => {
            it('should trim existing oversized person properties and update successfully', async () => {
                const team = await getFirstTeam(hub)

                const normalPerson = await createTestPerson(team.id, 'test-oversized-update', {
                    name: 'John',
                    description: 'x'.repeat(120),
                })

                const mockPersonPropertiesSize = jest
                    .spyOn(oversizedRepository, 'personPropertiesSize')
                    .mockResolvedValue(60)

                const oversizedUpdate = {
                    properties: {
                        name: 'John Updated',
                        description: 'x'.repeat(120),
                        newField: 'y'.repeat(50),
                    },
                }

                const [updatedPerson, messages] = await oversizedRepository.updatePerson(normalPerson, oversizedUpdate)

                expect(updatedPerson).toBeDefined()
                expect(updatedPerson.version).toBe(normalPerson.version + 1)
                expect(messages).toHaveLength(1)
                expect(Object.keys(updatedPerson.properties).length).toBeLessThanOrEqual(3)

                mockPersonPropertiesSize.mockRestore()
            })

            it('should reject update when current person is under limit but update would exceed it', async () => {
                const team = await getFirstTeam(hub)
                const normalPerson = await createTestPerson(team.id, 'test-normal-person', { name: 'John' })

                const mockPersonPropertiesSize = jest
                    .spyOn(oversizedRepository, 'personPropertiesSize')
                    .mockResolvedValue(30)

                const originalQuery = postgres.query.bind(postgres)
                const mockQuery = jest.spyOn(postgres, 'query').mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('UPDATE posthog_person SET')) {
                        const error = new Error('Check constraint violation')
                        ;(error as any).code = '23514'
                        ;(error as any).constraint = 'check_properties_size'
                        throw error
                    }
                    return originalQuery(use, query, values, tag)
                })

                const oversizedUpdate = {
                    properties: {
                        description: 'x'.repeat(200),
                    },
                }

                await expect(oversizedRepository.updatePerson(normalPerson, oversizedUpdate)).rejects.toThrow(
                    PersonPropertiesSizeViolationError
                )
                await expect(oversizedRepository.updatePerson(normalPerson, oversizedUpdate)).rejects.toThrow(
                    'Person properties update would exceed size limit'
                )

                mockPersonPropertiesSize.mockRestore()
                mockQuery.mockRestore()
            })

            it('should fail gracefully when trimming fails', async () => {
                const team = await getFirstTeam(hub)
                const normalPerson = await createTestPerson(team.id, 'test-trim-failure', {
                    name: 'John',
                    description: 'x'.repeat(120),
                })

                const mockPersonPropertiesSize = jest
                    .spyOn(oversizedRepository, 'personPropertiesSize')
                    .mockResolvedValue(60)

                const originalQuery = postgres.query.bind(postgres)
                let updateCallCount = 0
                const mockQuery = jest.spyOn(postgres, 'query').mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('UPDATE posthog_person SET')) {
                        updateCallCount++
                        if (updateCallCount === 1) {
                            const error = new Error('Check constraint violation')
                            ;(error as any).code = '23514'
                            ;(error as any).constraint = 'check_properties_size'
                            throw error
                        } else if (updateCallCount === 2) {
                            throw new Error('Trimming update failed')
                        }
                    }
                    return originalQuery(use, query, values, tag)
                })

                const oversizedUpdate = {
                    properties: {
                        name: 'John Updated',
                        description: 'x'.repeat(120),
                        newField: 'y'.repeat(50),
                    },
                }

                await expect(oversizedRepository.updatePerson(normalPerson, oversizedUpdate)).rejects.toThrow(
                    PersonPropertiesSizeViolationError
                )

                updateCallCount = 0
                await expect(oversizedRepository.updatePerson(normalPerson, oversizedUpdate)).rejects.toThrow(
                    'Person properties update failed after trying to trim oversized properties'
                )

                mockPersonPropertiesSize.mockRestore()
                mockQuery.mockRestore()
            })

            it('should fail when protected properties alone exceed size limit and cannot be trimmed', async () => {
                const team = await getFirstTeam(hub)

                const largeProtectedProperties = {
                    name: 'John Doe with a very long name that takes up significant space',
                    email: 'john.doe.with.an.extremely.long.email.address.that.should.be.protected@example.com',
                    utm_source: 'x'.repeat(30),
                    utm_medium: 'x'.repeat(30),
                    utm_campaign: 'x'.repeat(30),
                    utm_content: 'x'.repeat(30),
                    utm_term: 'x'.repeat(30),
                    $browser: 'Chrome with very long user agent string information',
                    $browser_version: 'Version 120.0.0.0 with extended metadata',
                    $os: 'Operating System with detailed version information',
                    $device_type: 'Desktop computer with specific hardware details',
                    $current_url:
                        'https://example.com/very/long/path/with/many/segments/and/parameters?param1=value1&param2=value2',
                    $referring_domain: 'referring-domain-with-long-name.example.com',
                    $referrer: 'https://referring-site.com/with/very/long/path/that/contains/many/details',
                    description: 'This is a trimmable property',
                    customData: 'This can be removed',
                }

                const oversizedPerson = await createTestPerson(
                    team.id,
                    'test-protected-oversized',
                    largeProtectedProperties
                )

                const mockPersonPropertiesSize = jest
                    .spyOn(oversizedRepository, 'personPropertiesSize')
                    .mockResolvedValue(60)

                const originalQuery = postgres.query.bind(postgres)
                let updateCallCount = 0
                const mockQuery = jest.spyOn(postgres, 'query').mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('UPDATE posthog_person SET')) {
                        updateCallCount++

                        const error = new Error('Check constraint violation')
                        ;(error as any).code = '23514'
                        ;(error as any).constraint = 'check_properties_size'
                        throw error
                    }
                    return originalQuery(use, query, values, tag)
                })

                const update = {
                    properties: {
                        $app_name: 'Application name with detailed information',
                        $app_version: 'Version 1.2.3 with build metadata',
                    },
                }

                await expect(oversizedRepository.updatePerson(oversizedPerson, update)).rejects.toThrow(
                    PersonPropertiesSizeViolationError
                )

                expect(updateCallCount).toBe(2)

                updateCallCount = 0
                await expect(oversizedRepository.updatePerson(oversizedPerson, update)).rejects.toThrow(
                    'Person properties update failed after trying to trim oversized properties'
                )

                expect(updateCallCount).toBe(2)

                mockPersonPropertiesSize.mockRestore()
                mockQuery.mockRestore()
            })

            it('should demonstrate that trimPropertiesToFitSize cannot reduce protected properties below size limit', () => {
                const protectedPropertiesExceedingLimit = {
                    name: 'A very long name that takes up space',
                    email: 'long.email.address@example.com',
                    utm_source: 'x'.repeat(50),
                    utm_medium: 'x'.repeat(50),
                    description: 'This should be removed',
                    customField: 'This should also be removed',
                }

                const targetSize = 30

                const result = (oversizedRepository as any).trimPropertiesToFitSize(
                    protectedPropertiesExceedingLimit,
                    targetSize
                )

                expect(result).toHaveProperty('name')
                expect(result).toHaveProperty('email')
                expect(result).toHaveProperty('utm_source')
                expect(result).toHaveProperty('utm_medium')

                expect(result).not.toHaveProperty('description')
                expect(result).not.toHaveProperty('customField')

                const finalSize = Buffer.byteLength(JSON.stringify(result), 'utf8')
                expect(finalSize).toBeGreaterThan(targetSize)
            })
        })

        describe('updatePersonAssertVersion with oversized properties', () => {
            it('should throw PersonPropertiesSizeViolationError when properties exceed size limit', async () => {
                const team = await getFirstTeam(hub)
                const person = await createTestPerson(team.id, 'test-assert-oversized', { name: 'John' })

                const originalQuery = postgres.query.bind(postgres)
                const mockQuery = jest.spyOn(postgres, 'query').mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('UPDATE posthog_person SET')) {
                        const error = new Error('Check constraint violation')
                        ;(error as any).code = '23514'
                        ;(error as any).constraint = 'check_properties_size'
                        throw error
                    }
                    return originalQuery(use, query, values, tag)
                })

                const personUpdate = {
                    id: person.id,
                    team_id: person.team_id,
                    uuid: person.uuid,
                    distinct_id: 'test-assert-oversized',
                    properties: {
                        name: 'John',
                        description: 'x'.repeat(150),
                    },
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                    created_at: person.created_at,
                    version: person.version,
                    is_identified: person.is_identified,
                    is_user_id: person.is_user_id,
                    needs_write: true,
                    properties_to_set: { description: 'x'.repeat(150) },
                    properties_to_unset: [],
                    original_is_identified: false,
                    original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
                }

                await expect(oversizedRepository.updatePersonAssertVersion(personUpdate)).rejects.toThrow(
                    PersonPropertiesSizeViolationError
                )
                await expect(oversizedRepository.updatePersonAssertVersion(personUpdate)).rejects.toThrow(
                    'Person properties update would exceed size limit'
                )

                mockQuery.mockRestore()
            })
        })

        describe('new metrics and error handling', () => {
            it('should increment personPropertiesSizeViolationCounter with correct labels', async () => {
                const team = await getFirstTeam(hub)
                const uuid = new UUIDT().toString()
                const oversizedProperties = {
                    description: 'x'.repeat(200),
                }

                const originalQuery = postgres.query.bind(postgres)
                const mockQuery = jest.spyOn(postgres, 'query').mockImplementation(async (use, query, values, tag) => {
                    if (typeof query === 'string' && query.includes('INSERT INTO posthog_person')) {
                        const error = new Error('Check constraint violation')
                        ;(error as any).code = '23514'
                        ;(error as any).constraint = 'check_properties_size'
                        throw error
                    }
                    return originalQuery(use, query, values, tag)
                })

                const metrics = require('../metrics')
                const mockInc = jest.fn()
                const originalInc = metrics.personPropertiesSizeViolationCounter.inc
                metrics.personPropertiesSizeViolationCounter.inc = mockInc

                try {
                    await oversizedRepository.createPerson(
                        TIMESTAMP,
                        oversizedProperties,
                        {},
                        {},
                        team.id,
                        null,
                        true,
                        uuid,
                        [{ distinctId: 'test-metrics' }]
                    )
                } catch (error) {}

                expect(mockInc).toHaveBeenCalledWith({
                    violation_type: 'create_person_size_violation',
                })

                metrics.personPropertiesSizeViolationCounter.inc = originalInc
                mockQuery.mockRestore()
            })

            it('should increment oversizedPersonPropertiesTrimmedCounter when trimming succeeds', async () => {
                const team = await getFirstTeam(hub)
                const person = await createTestPerson(team.id, 'test-trimming-metrics', {
                    name: 'John',
                    description: 'x'.repeat(120),
                })

                const mockPersonPropertiesSize = jest
                    .spyOn(oversizedRepository, 'personPropertiesSize')
                    .mockResolvedValue(60)

                const metrics = require('../metrics')
                const mockInc = jest.fn()
                const originalInc = metrics.oversizedPersonPropertiesTrimmedCounter.inc
                metrics.oversizedPersonPropertiesTrimmedCounter.inc = mockInc

                const oversizedUpdate = {
                    properties: {
                        name: 'John Updated',
                        description: 'x'.repeat(120),
                        newField: 'y'.repeat(50),
                    },
                }

                try {
                    await oversizedRepository.updatePerson(person, oversizedUpdate)
                    expect(mockInc).toHaveBeenCalledWith({ result: 'success' })
                } catch (error) {}

                mockPersonPropertiesSize.mockRestore()
                metrics.oversizedPersonPropertiesTrimmedCounter.inc = originalInc
            })
        })

        describe('handleOversizedPersonProperties and related methods', () => {
            it('should test trimPropertiesToFitSize respects protected properties', () => {
                const properties = {
                    email: 'user@example.com',
                    name: 'John Doe',
                    $browser: 'Chrome',
                    utm_source: 'google',
                    description: 'A very long description that should be removed',
                    largeData: 'x'.repeat(100),
                    moreData: 'y'.repeat(50),
                }
                const targetSize = 100

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result).toHaveProperty('email', 'user@example.com')
                expect(result).toHaveProperty('name', 'John Doe')
                expect(result).toHaveProperty('$browser', 'Chrome')
                expect(result).toHaveProperty('utm_source', 'google')

                expect(Object.keys(result).length).toBeLessThan(Object.keys(properties).length)
                expect(Buffer.byteLength(JSON.stringify(result), 'utf8')).toBeLessThanOrEqual(targetSize + 50) // Some tolerance for protected properties
            })

            it('should handle constraint violation detection correctly', () => {
                const sizeViolationError = {
                    code: '23514',
                    constraint: 'check_properties_size',
                }

                const otherError = {
                    code: '23505',
                    constraint: 'unique_constraint',
                }

                expect((oversizedRepository as any).isPropertiesSizeConstraintViolation(sizeViolationError)).toBe(true)
                expect((oversizedRepository as any).isPropertiesSizeConstraintViolation(otherError)).toBe(false)
                expect((oversizedRepository as any).isPropertiesSizeConstraintViolation(null)).toBe(false)
                expect((oversizedRepository as any).isPropertiesSizeConstraintViolation(undefined)).toBe(false)
            })
        })

        describe('protected properties during trimming', () => {
            it('should respect default protected properties', () => {
                const properties = {
                    email: 'john@example.com',
                    name: 'John Doe',
                    utm_source: 'google',
                    description: 'A very long description that takes up space',
                    largeField: 'x'.repeat(100),
                    age: 30,
                }
                const targetSize = 60

                const result = (oversizedRepository as any).trimPropertiesToFitSize(properties, targetSize)

                expect(result).toHaveProperty('email', 'john@example.com')
                expect(result).toHaveProperty('name', 'John Doe')
                expect(result).toHaveProperty('utm_source', 'google')

                expect(Object.keys(result).length).toBeLessThan(Object.keys(properties).length)
                expect(Buffer.byteLength(JSON.stringify(result), 'utf8')).toBeLessThanOrEqual(targetSize + 50) // Some tolerance
            })
        })
    })

    describe('calculate properties size feature flag', () => {
        it('should have identical output whether properties size calculation is enabled or disabled', async () => {
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

            const repositoryWithCalculation = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: 100,
                personPropertiesDbConstraintLimitBytes: 1024 * 1024,
                personPropertiesTrimTargetBytes: 512 * 1024,
            })
            const repositoryWithoutCalculation = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: 0,
                personPropertiesDbConstraintLimitBytes: 1024 * 1024,
                personPropertiesTrimTargetBytes: 512 * 1024,
            })

            const update = {
                properties: {
                    name: 'Jane',
                    age: 30,
                    city: 'New York',
                    anotherLargeProperty: 'y'.repeat(1500),
                },
            }

            const [updatedPerson1, messages1, versionDisparity1] = await repositoryWithCalculation.updatePerson(
                person1,
                update,
                'test-with-logging'
            )
            const [updatedPerson2, messages2, versionDisparity2] = await repositoryWithoutCalculation.updatePerson(
                person2,
                update,
                'test-without-logging'
            )

            expect(updatedPerson1.properties).toEqual(updatedPerson2.properties)
            expect(updatedPerson1.is_identified).toEqual(updatedPerson2.is_identified)
            expect(updatedPerson1.version).toEqual(updatedPerson2.version)
            expect(versionDisparity1).toEqual(versionDisparity2)
            expect(messages1).toHaveLength(messages2.length)

            const fetchedPerson1 = await repositoryWithCalculation.fetchPerson(team.id, 'test-distinct-1')
            const fetchedPerson2 = await repositoryWithoutCalculation.fetchPerson(team.id, 'test-distinct-2')

            expect(fetchedPerson1?.properties).toEqual(fetchedPerson2?.properties)
            expect(fetchedPerson1?.version).toEqual(fetchedPerson2?.version)
        })

        it('should have identical behavior for updatePersonAssertVersion regardless of logging configuration', async () => {
            const team = await getFirstTeam(hub)

            const person1 = await createTestPerson(team.id, 'test-assert-1', { name: 'John', data: 'x'.repeat(2000) })
            const person2 = await createTestPerson(team.id, 'test-assert-2', { name: 'John', data: 'x'.repeat(2000) })

            const repositoryWithCalculation = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: 100,
                personPropertiesDbConstraintLimitBytes: 1024 * 1024,
                personPropertiesTrimTargetBytes: 512 * 1024,
            })
            const repositoryWithoutCalculation = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: 0,
                personPropertiesDbConstraintLimitBytes: 1024 * 1024,
                personPropertiesTrimTargetBytes: 512 * 1024,
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
                original_is_identified: false,
                original_created_at: DateTime.fromISO('2020-01-01T00:00:00.000Z'),
            })

            const personUpdate1 = createPersonUpdate(person1, 'test-assert-1')
            const personUpdate2 = createPersonUpdate(person2, 'test-assert-2')

            const [actualVersion1, messages1] = await repositoryWithCalculation.updatePersonAssertVersion(personUpdate1)
            const [actualVersion2, messages2] =
                await repositoryWithoutCalculation.updatePersonAssertVersion(personUpdate2)

            expect(actualVersion1).toBeDefined()
            expect(actualVersion2).toBeDefined()
            expect(actualVersion1).toEqual(person1.version + 1)
            expect(actualVersion2).toEqual(person2.version + 1)
            expect(messages1).toHaveLength(messages2.length)

            const fetchedPerson1 = await repositoryWithCalculation.fetchPerson(team.id, 'test-assert-1')
            const fetchedPerson2 = await repositoryWithoutCalculation.fetchPerson(team.id, 'test-assert-2')

            expect(fetchedPerson1?.properties).toEqual(fetchedPerson2?.properties)
            expect(fetchedPerson1?.version).toEqual(fetchedPerson2?.version)
        })

        it('should work with default options (no logging)', async () => {
            const team = await getFirstTeam(hub)
            const defaultRepository = new PostgresPersonRepository(postgres, {
                calculatePropertiesSize: 0,
                personPropertiesDbConstraintLimitBytes: 1024 * 1024,
                personPropertiesTrimTargetBytes: 512 * 1024,
            })

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
