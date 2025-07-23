import { DateTime } from 'luxon'

import { resetTestDatabase } from '../../../../tests/helpers/sql'
import { Hub, Team } from '../../../types'
import { closeHub, createHub } from '../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { parseJSON } from '../../../utils/json-parse'
import { UUIDT } from '../../../utils/utils'
import { BasePersonRepository } from './base-person-repository'

jest.mock('../../../utils/logger')

describe('BasePersonRepository', () => {
    let hub: Hub
    let postgres: PostgresRouter
    let repository: BasePersonRepository

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        postgres = hub.db.postgres
        repository = new BasePersonRepository(postgres)

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
