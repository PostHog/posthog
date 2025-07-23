import { DateTime } from 'luxon'

import { resetTestDatabase } from '../../../../tests/helpers/sql'
import { Hub, Team } from '../../../types'
import { DB } from '../../../utils/db/db'
import { closeHub, createHub } from '../../../utils/db/hub'
import { PostgresRouter, PostgresUse } from '../../../utils/db/postgres'
import { UUIDT } from '../../../utils/utils'
import { BasePersonRepository } from './base-person-repository'

jest.mock('../../../utils/logger')

describe('BasePersonRepository', () => {
    let hub: Hub
    let db: DB
    let postgres: PostgresRouter
    let repository: BasePersonRepository

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        db = hub.db
        postgres = db.postgres
        repository = new BasePersonRepository(postgres)

        const redis = await hub.redisPool.acquire()
        await redis.flushdb()
        await db.redisPool.release(redis)
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.clearAllMocks()
    })

    const TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

    // Helper function to create a person with all the necessary setup
    async function createTestPerson(teamId: number, distinctId: string, properties: Record<string, any> = {}) {
        const uuid = new UUIDT().toString()
        const [createdPerson, kafkaMessages] = await db.createPerson(
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
