import { DateTime, Settings } from 'luxon'

import { Clickhouse } from '../../../../../tests/helpers/clickhouse'
import { resetTestDatabase } from '../../../../../tests/helpers/sql'
import { Hub, PropertyOperator, Team } from '../../../../types'
import { ClickHouseRouter } from '../../../../utils/db/clickhouse'
import { closeHub, createHub } from '../../../../utils/db/hub'
import { PostgresUse } from '../../../../utils/db/postgres'
import { UUIDT } from '../../../../utils/utils'
import { ClickHousePersonRepository } from './clickhouse-person-repository'

jest.mock('../../../../utils/logger')

describe('ClickHousePersonRepository', () => {
    let hub: Hub
    let clickHouseRouter: ClickHouseRouter
    let repository: ClickHousePersonRepository
    let clickhouse: Clickhouse

    async function executeClickHouseTestQuery(query: string): Promise<void> {
        await clickhouse.exec(query)
    }

    beforeAll(() => {
        clickhouse = Clickhouse.create()
    })

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        await clickhouse.resetTestDatabase()
        clickHouseRouter = new ClickHouseRouter(hub)
        clickHouseRouter.initialize()
        repository = new ClickHousePersonRepository(clickHouseRouter)
    })

    afterEach(async () => {
        await clickHouseRouter.close()
        await closeHub(hub)
        jest.clearAllMocks()
    })

    afterAll(() => {
        clickhouse.close()
    })

    const TIMESTAMP = DateTime.fromISO('2024-01-15T10:30:00.000Z').toUTC()

    async function insertPersonIntoClickHouse(
        teamId: number,
        personId: string,
        properties: Record<string, any> = {},
        isIdentified: number = 1,
        distinctId?: string
    ) {
        const timestamp = TIMESTAMP.toFormat('yyyy-MM-dd HH:mm:ss')
        const propertiesJson = JSON.stringify(properties)

        await executeClickHouseTestQuery(
            `INSERT INTO person (id, team_id, properties, is_identified, is_deleted, created_at, _timestamp, _offset, version) VALUES ('${personId}', ${teamId}, '${propertiesJson}', ${isIdentified}, 0, '${timestamp}', '${timestamp}', 0, 0)`
        )

        if (distinctId) {
            await executeClickHouseTestQuery(
                `INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset) VALUES (${teamId}, '${distinctId}', '${personId}', 0, 0, '${timestamp}', 0)`
            )
        }
    }

    describe('countPersonsByProperties()', () => {
        let team: Team

        beforeEach(async () => {
            team = await getFirstTeam(hub)
        })

        it('should return 0 when no persons exist', async () => {
            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: 'test@example.com', operator: PropertyOperator.Exact, type: 'person' },
                ],
            })

            expect(count).toBe(0)
        })

        it('should return total count when properties array is empty', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'user1@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user2@example.com' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [],
            })

            expect(count).toBe(2)
        })

        it('should count persons with exact property match', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' })
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' })
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'admin' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(count).toBe(2)
        })

        it('should count persons with exact property match using array value (IN logic)', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' })
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' })
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'moderator' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'role', value: ['admin', 'moderator'], operator: PropertyOperator.Exact, type: 'person' },
                ],
            })

            expect(count).toBe(2)
        })

        it('should count persons with is_not operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' })
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' })
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'user' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.IsNot, type: 'person' }],
            })

            expect(count).toBe(2)
        })

        it('should count persons with is_not operator using array value (NOT IN logic)', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()
            const personId4 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' })
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' })
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'moderator' })
            await insertPersonIntoClickHouse(team.id, personId4, { role: 'guest' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'role', value: ['admin', 'moderator'], operator: PropertyOperator.IsNot, type: 'person' },
                ],
            })

            expect(count).toBe(2) // user and guest
        })

        it('should count persons with is_set operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'user1@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { name: 'User 2' })
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'user3@example.com' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'email', value: null, operator: PropertyOperator.IsSet, type: 'person' }],
            })

            expect(count).toBe(2)
        })

        it('should count persons with is_not_set operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'user1@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { name: 'User 2' })
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'user3@example.com' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'email', value: null, operator: PropertyOperator.IsNotSet, type: 'person' }],
            })

            expect(count).toBe(1)
        })

        it('should count persons with icontains operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' })
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'moderator@Example.com' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'email', value: 'example', operator: PropertyOperator.IContains, type: 'person' }],
            })

            expect(count).toBe(2)
        })

        it('should count persons with not_icontains operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' })
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'moderator@Example.com' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: 'example', operator: PropertyOperator.NotIContains, type: 'person' },
                ],
            })

            expect(count).toBe(1)
        })

        it('should count persons with regex operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' })
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'admin@test.org' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: '^admin@.*\\.com$', operator: PropertyOperator.Regex, type: 'person' },
                ],
            })

            expect(count).toBe(1)
        })

        it('should count persons with not_regex operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' })
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' })
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'admin@test.org' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: '^admin@.*\\.com$', operator: PropertyOperator.NotRegex, type: 'person' },
                ],
            })

            expect(count).toBe(2)
        })

        it('should count persons with gt (greater than) operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { age: '25' })
            await insertPersonIntoClickHouse(team.id, personId2, { age: '35' })
            await insertPersonIntoClickHouse(team.id, personId3, { age: '45' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'age', value: '30', operator: PropertyOperator.GreaterThan, type: 'person' }],
            })

            expect(count).toBe(2)
        })

        it('should count persons with lt (less than) operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { age: '25' })
            await insertPersonIntoClickHouse(team.id, personId2, { age: '35' })
            await insertPersonIntoClickHouse(team.id, personId3, { age: '45' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'age', value: '40', operator: PropertyOperator.LessThan, type: 'person' }],
            })

            expect(count).toBe(2)
        })

        it('should count persons with is_date_before operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-01-01 00:00:00' })
            await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-01 00:00:00' })
            await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-12-01 00:00:00' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    {
                        key: 'signup_date',
                        value: '2024-07-01 00:00:00',
                        operator: PropertyOperator.IsDateBefore,
                        type: 'person',
                    },
                ],
            })

            expect(count).toBe(2)
        })

        it('should count persons with is_date_after operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-01-01 00:00:00' })
            await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-01 00:00:00' })
            await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-12-01 00:00:00' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    {
                        key: 'signup_date',
                        value: '2024-05-01 00:00:00',
                        operator: PropertyOperator.IsDateAfter,
                        type: 'person',
                    },
                ],
            })

            expect(count).toBe(2)
        })

        it('should count persons with relative is_date_before operator values', async () => {
            const previousNow = Settings.now
            Settings.now = () => new Date('2024-07-01T00:00:00.000Z').valueOf()

            try {
                const personId1 = new UUIDT().toString()
                const personId2 = new UUIDT().toString()
                const personId3 = new UUIDT().toString()

                await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-06-29 00:00:00' })
                await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-30 00:00:00' })
                await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-07-01 00:00:00' })

                const count = await repository.countPersonsByProperties({
                    teamId: team.id,
                    properties: [
                        {
                            key: 'signup_date',
                            value: '-24h',
                            operator: PropertyOperator.IsDateBefore,
                            type: 'person',
                        },
                    ],
                })

                expect(count).toBe(1)
            } finally {
                Settings.now = previousNow
            }
        })

        it('should count persons with relative is_date_after operator values', async () => {
            const previousNow = Settings.now
            Settings.now = () => new Date('2024-07-01T00:00:00.000Z').valueOf()

            try {
                const personId1 = new UUIDT().toString()
                const personId2 = new UUIDT().toString()
                const personId3 = new UUIDT().toString()

                await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-06-29 00:00:00' })
                await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-30 00:00:00' })
                await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-07-01 00:00:00' })

                const count = await repository.countPersonsByProperties({
                    teamId: team.id,
                    properties: [
                        {
                            key: 'signup_date',
                            value: '24h',
                            operator: PropertyOperator.IsDateAfter,
                            type: 'person',
                        },
                    ],
                })

                expect(count).toBe(1)
            } finally {
                Settings.now = previousNow
            }
        })

        it('should count persons with multiple property filters (AND condition)', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin', active: 'true' })
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user', active: 'true' })
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'admin', active: 'false' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' },
                    { key: 'active', value: 'true', operator: PropertyOperator.Exact, type: 'person' },
                ],
            })

            expect(count).toBe(1)
        })

        it('should handle null values correctly', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { name: null })
            await insertPersonIntoClickHouse(team.id, personId2, { name: 'John' })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'name', value: null, operator: PropertyOperator.Exact, type: 'person' }],
            })

            // null normalizes to empty string
            expect(count).toBe(1)
        })

        it('should handle numeric values as strings', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { count: 42 })
            await insertPersonIntoClickHouse(team.id, personId2, { count: 100 })

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'count', value: '42', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(count).toBe(1)
        })

        it('should not count deleted persons', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' })

            // Insert deleted person
            const timestamp = TIMESTAMP.toFormat('yyyy-MM-dd HH:mm:ss')
            await executeClickHouseTestQuery(
                `INSERT INTO person (id, team_id, properties, is_identified, is_deleted, created_at, _timestamp, _offset, version) VALUES ('${personId2}', ${team.id}, '${JSON.stringify({ role: 'admin' })}', 1, 1, '${timestamp}', '${timestamp}', 0, 0)`
            )

            const count = await repository.countPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(count).toBe(1)
        })
    })

    describe('fetchPersonsByProperties()', () => {
        let team: Team

        beforeEach(async () => {
            team = await getFirstTeam(hub)
        })

        it('should return empty array when no persons match', async () => {
            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    {
                        key: 'email',
                        value: 'nonexistent@example.com',
                        operator: PropertyOperator.Exact,
                        type: 'person',
                    },
                ],
            })

            expect(persons).toEqual([])
        })

        it('should fetch persons with exact property match', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0]).toMatchObject({
                id: personId1,
                team_id: team.id,
                properties: { role: 'admin' },
                is_identified: true,
                distinct_id: 'distinct1',
            })
        })

        it('should fetch persons with exact property match using array value (IN logic)', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'moderator' }, 1, 'distinct3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'role', value: ['admin', 'moderator'], operator: PropertyOperator.Exact, type: 'person' },
                ],
            })

            expect(persons).toHaveLength(2)
            const personIds = persons.map((p) => p.id).sort()
            expect(personIds).toEqual([personId1, personId3].sort())
        })

        it('should fetch persons with is_not operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.IsNot, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId2)
        })

        it('should fetch persons with is_not operator using array value (NOT IN logic)', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()
            const personId4 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'moderator' }, 1, 'distinct3')
            await insertPersonIntoClickHouse(team.id, personId4, { role: 'guest' }, 1, 'distinct4')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'role', value: ['admin', 'moderator'], operator: PropertyOperator.IsNot, type: 'person' },
                ],
            })

            expect(persons).toHaveLength(2)
            const personIds = persons.map((p) => p.id).sort()
            expect(personIds).toEqual([personId2, personId4].sort())
        })

        it('should fetch persons with is_set operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'user@example.com' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { name: 'User' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'email', value: null, operator: PropertyOperator.IsSet, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should fetch persons with is_not_set operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'user@example.com' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { name: 'User' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'email', value: null, operator: PropertyOperator.IsNotSet, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId2)
        })

        it('should fetch persons with icontains operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@Example.com' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'email', value: 'example', operator: PropertyOperator.IContains, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should fetch persons with not_icontains operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'moderator@Example.com' }, 1, 'distinct3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: 'example', operator: PropertyOperator.NotIContains, type: 'person' },
                ],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId2)
        })

        it('should fetch persons with regex operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'admin@test.org' }, 1, 'distinct3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: '^admin@.*\\.com$', operator: PropertyOperator.Regex, type: 'person' },
                ],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should fetch persons with not_regex operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { email: 'admin@example.com' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { email: 'user@test.com' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { email: 'admin@test.org' }, 1, 'distinct3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    {
                        key: 'email',
                        value: '^admin@.*\\.com$',
                        operator: PropertyOperator.NotRegex,
                        type: 'person',
                    },
                ],
            })

            expect(persons).toHaveLength(2)
            const personIds = persons.map((p) => p.id).sort()
            expect(personIds).toEqual([personId2, personId3].sort())
        })

        it('should fetch persons with gt operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { age: '25' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { age: '45' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'age', value: '30', operator: PropertyOperator.GreaterThan, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId2)
        })

        it('should fetch persons with lt operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { age: '25' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { age: '45' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'age', value: '40', operator: PropertyOperator.LessThan, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should fetch persons with is_date_before operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-01-01 00:00:00' }, 1, 'd1')
            await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-01 00:00:00' }, 1, 'd2')
            await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-12-01 00:00:00' }, 1, 'd3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    {
                        key: 'signup_date',
                        value: '2024-07-01 00:00:00',
                        operator: PropertyOperator.IsDateBefore,
                        type: 'person',
                    },
                ],
            })

            expect(persons).toHaveLength(2)
            const personIds = persons.map((p) => p.id).sort()
            expect(personIds).toEqual([personId1, personId2].sort())
        })

        it('should fetch persons with is_date_after operator', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-01-01 00:00:00' }, 1, 'd1')
            await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-01 00:00:00' }, 1, 'd2')
            await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-12-01 00:00:00' }, 1, 'd3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    {
                        key: 'signup_date',
                        value: '2024-05-01 00:00:00',
                        operator: PropertyOperator.IsDateAfter,
                        type: 'person',
                    },
                ],
            })

            expect(persons).toHaveLength(2)
            const personIds = persons.map((p) => p.id).sort()
            expect(personIds).toEqual([personId2, personId3].sort())
        })

        it('should fetch persons with relative is_date_before operator values', async () => {
            const previousNow = Settings.now
            Settings.now = () => new Date('2024-07-01T00:00:00.000Z').valueOf()

            try {
                const personId1 = new UUIDT().toString()
                const personId2 = new UUIDT().toString()
                const personId3 = new UUIDT().toString()

                await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-06-29 00:00:00' }, 1, 'd1')
                await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-30 00:00:00' }, 1, 'd2')
                await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-07-01 00:00:00' }, 1, 'd3')

                const persons = await repository.fetchPersonsByProperties({
                    teamId: team.id,
                    properties: [
                        {
                            key: 'signup_date',
                            value: '-24h',
                            operator: PropertyOperator.IsDateBefore,
                            type: 'person',
                        },
                    ],
                })

                expect(persons).toHaveLength(1)
                expect(persons[0].id).toBe(personId1)
            } finally {
                Settings.now = previousNow
            }
        })

        it('should fetch persons with relative is_date_after operator values', async () => {
            const previousNow = Settings.now
            Settings.now = () => new Date('2024-07-01T00:00:00.000Z').valueOf()

            try {
                const personId1 = new UUIDT().toString()
                const personId2 = new UUIDT().toString()
                const personId3 = new UUIDT().toString()

                await insertPersonIntoClickHouse(team.id, personId1, { signup_date: '2024-06-29 00:00:00' }, 1, 'd1')
                await insertPersonIntoClickHouse(team.id, personId2, { signup_date: '2024-06-30 00:00:00' }, 1, 'd2')
                await insertPersonIntoClickHouse(team.id, personId3, { signup_date: '2024-07-01 00:00:00' }, 1, 'd3')

                const persons = await repository.fetchPersonsByProperties({
                    teamId: team.id,
                    properties: [
                        {
                            key: 'signup_date',
                            value: '24h',
                            operator: PropertyOperator.IsDateAfter,
                            type: 'person',
                        },
                    ],
                })

                expect(persons).toHaveLength(1)
                expect(persons[0].id).toBe(personId3)
            } finally {
                Settings.now = previousNow
            }
        })

        it('should handle null values correctly', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { name: null }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { name: 'John' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'name', value: null, operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should handle numeric values as strings', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { count: 42 }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { count: 100 }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'count', value: '42', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should respect limit parameter', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'user' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'user' }, 1, 'distinct3')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'user', operator: PropertyOperator.Exact, type: 'person' }],
                options: { limit: 2 },
            })

            expect(persons).toHaveLength(2)
        })

        it('should respect cursor parameter for pagination', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()
            const allPersonIds = [personId1, personId2, personId3]

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'user' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'user' }, 1, 'distinct3')

            // First page
            const firstPage = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'user', operator: PropertyOperator.Exact, type: 'person' }],
                options: { limit: 2 },
            })

            expect(firstPage).toHaveLength(2)
            const firstPageIds = firstPage.map((p) => p.id)

            // Second page using cursor
            const lastPersonId = firstPage[firstPage.length - 1].id
            const secondPage = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'user', operator: PropertyOperator.Exact, type: 'person' }],
                options: { cursor: lastPersonId, limit: 10 },
            })

            expect(secondPage.length).toBeGreaterThanOrEqual(1)

            // Ensure no duplicates between pages - cursor should exclude already seen results
            const secondPageIds = secondPage.map((p) => p.id)
            const overlap = firstPageIds.filter((id) => secondPageIds.includes(id))
            expect(overlap).toHaveLength(0)

            // Verify we got all 3 persons across both pages
            const allFetchedIds = [...firstPageIds, ...secondPageIds]
            allPersonIds.forEach((id) => {
                expect(allFetchedIds).toContain(id)
            })
        })

        it('should fetch persons with multiple property filters (AND condition)', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin', active: 'true' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'admin', active: 'false' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' },
                    { key: 'active', value: 'true', operator: PropertyOperator.Exact, type: 'person' },
                ],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should return empty array when properties array is empty', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' }, 1, 'distinct1')
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [],
            })

            // When no filters, should return all persons (up to limit)
            expect(persons.length).toBeGreaterThanOrEqual(2)
        })

        it('should include all required InternalPersonWithDistinctId fields', async () => {
            const personId = new UUIDT().toString()
            const properties = { email: 'test@example.com', name: 'Test User' }

            await insertPersonIntoClickHouse(team.id, personId, properties, 1, 'test-distinct-id')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [
                    { key: 'email', value: 'test@example.com', operator: PropertyOperator.Exact, type: 'person' },
                ],
            })

            expect(persons).toHaveLength(1)
            const person = persons[0]

            // Check all required fields from InternalPersonWithDistinctId
            expect(person).toMatchObject({
                id: personId,
                uuid: personId,
                team_id: team.id,
                properties: properties,
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                is_identified: true,
                version: 0,
                distinct_id: 'test-distinct-id',
            })
            expect(person.created_at).toBeInstanceOf(DateTime)
        })

        it('should not fetch deleted persons', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'admin' }, 1, 'distinct1')

            // Insert deleted person
            const timestamp = TIMESTAMP.toFormat('yyyy-MM-dd HH:mm:ss')
            await executeClickHouseTestQuery(
                `INSERT INTO person (id, team_id, properties, is_identified, is_deleted, created_at, _timestamp, _offset, version) VALUES ('${personId2}', ${team.id}, '${JSON.stringify({ role: 'admin' })}', 1, 1, '${timestamp}', '${timestamp}', 0, 0)`
            )

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId1)
        })

        it('should not return persons with deleted distinct_id', async () => {
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const timestamp = TIMESTAMP.toFormat('yyyy-MM-dd HH:mm:ss')

            // Insert person 1 with a distinct_id that will be deleted
            await executeClickHouseTestQuery(
                `INSERT INTO person (id, team_id, properties, is_identified, is_deleted, created_at, _timestamp, _offset, version) VALUES ('${personId1}', ${team.id}, '${JSON.stringify({ role: 'admin' })}', 1, 0, '${timestamp}', '${timestamp}', 0, 0)`
            )
            await executeClickHouseTestQuery(
                `INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset) VALUES (${team.id}, 'distinct1', '${personId1}', 0, 0, '${timestamp}', 0)`
            )
            // Mark the distinct_id as deleted with a higher version
            await executeClickHouseTestQuery(
                `INSERT INTO person_distinct_id2 (team_id, distinct_id, person_id, is_deleted, version, _timestamp, _offset) VALUES (${team.id}, 'distinct1', '${personId1}', 1, 1, '${timestamp}', 0)`
            )

            // Insert person 2 with a non-deleted distinct_id for comparison
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'admin' }, 1, 'distinct2')

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'admin', operator: PropertyOperator.Exact, type: 'person' }],
            })

            // Should only return person2 since person1's distinct_id is deleted
            expect(persons).toHaveLength(1)
            expect(persons[0].id).toBe(personId2)
            expect(persons[0].distinct_id).toBe('distinct2')
        })

        it('should return persons ordered by id for consistent pagination', async () => {
            // Create 3 persons - don't pre-sort the IDs, let ClickHouse order them
            const personId1 = new UUIDT().toString()
            const personId2 = new UUIDT().toString()
            const personId3 = new UUIDT().toString()

            await insertPersonIntoClickHouse(team.id, personId1, { role: 'user' }, 1, `distinct-${personId1}`)
            await insertPersonIntoClickHouse(team.id, personId2, { role: 'user' }, 1, `distinct-${personId2}`)
            await insertPersonIntoClickHouse(team.id, personId3, { role: 'user' }, 1, `distinct-${personId3}`)

            const persons = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'user', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(persons).toHaveLength(3)

            // Verify all persons are present
            const fetchedIds = persons.map((p) => p.id)
            expect(fetchedIds).toContain(personId1)
            expect(fetchedIds).toContain(personId2)
            expect(fetchedIds).toContain(personId3)

            // Verify consistent ordering by fetching again - should get same order
            const persons2 = await repository.fetchPersonsByProperties({
                teamId: team.id,
                properties: [{ key: 'role', value: 'user', operator: PropertyOperator.Exact, type: 'person' }],
            })

            expect(persons2.map((p) => p.id)).toEqual(fetchedIds)
        })
    })

    describe('unimplemented methods', () => {
        it('should throw error for fetchPerson', async () => {
            await expect(repository.fetchPerson(1, 'distinct-id')).rejects.toThrow(
                'fetchPerson operation not yet supported in ClickHousePersonRepository'
            )
        })

        it('should throw error for fetchPersonsByDistinctIds', async () => {
            await expect(repository.fetchPersonsByDistinctIds([])).rejects.toThrow(
                'fetchPersonsByDistinctIds operation not yet supported in ClickHousePersonRepository'
            )
        })

        it('should throw error for createPerson', async () => {
            await expect(
                repository.createPerson(TIMESTAMP, {}, {}, {}, 1, null, false, new UUIDT().toString(), {
                    distinctId: 'test',
                })
            ).rejects.toThrow('Write operations not supported in ClickHousePersonRepository')
        })

        it('should throw error for updatePerson', async () => {
            const person = {
                id: new UUIDT().toString(),
                uuid: new UUIDT().toString(),
                team_id: 1,
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                is_identified: false,
                created_at: TIMESTAMP,
                version: 0,
                last_seen_at: null,
            }
            await expect(repository.updatePerson(person, {} as any)).rejects.toThrow(
                'Write operations not supported in ClickHousePersonRepository'
            )
        })

        it('should throw error for deletePerson', async () => {
            const person = {
                id: new UUIDT().toString(),
                uuid: new UUIDT().toString(),
                team_id: 1,
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                is_identified: false,
                created_at: TIMESTAMP,
                version: 0,
                last_seen_at: null,
            }
            await expect(repository.deletePerson(person)).rejects.toThrow(
                'Write operations not supported in ClickHousePersonRepository'
            )
        })

        it('should throw error for addDistinctId', async () => {
            const person = {
                id: new UUIDT().toString(),
                uuid: new UUIDT().toString(),
                team_id: 1,
                properties: {},
                properties_last_updated_at: {},
                properties_last_operation: {},
                is_user_id: null,
                is_identified: false,
                created_at: TIMESTAMP,
                version: 0,
                last_seen_at: null,
            }
            await expect(repository.addDistinctId(person, 'new-distinct-id', 0)).rejects.toThrow(
                'Write operations not supported in ClickHousePersonRepository'
            )
        })

        it('should throw error for addPersonlessDistinctId', async () => {
            await expect(repository.addPersonlessDistinctId(1, 'distinct-id')).rejects.toThrow(
                'Write operations not supported in ClickHousePersonRepository'
            )
        })
    })
})

// Helper function to get first team
async function getFirstTeam(hub: Hub): Promise<Team> {
    const teams = await hub.postgres.query(
        PostgresUse.COMMON_WRITE,
        'SELECT * FROM posthog_team LIMIT 1',
        [],
        'getFirstTeam'
    )
    return teams.rows[0]
}
