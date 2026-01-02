import { DateTime } from 'luxon'

import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Person, PropertyOperator, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'
import { PostgresPersonRepository } from '~/worker/ingestion/persons/repositories/postgres-person-repository'

import { PersonsManagerService } from './persons-manager.service'

describe('PersonsManager', () => {
    let hub: Hub
    let personRepository: PostgresPersonRepository
    let manager: PersonsManagerService
    let team: Team
    let team2: Team
    let persons: Person[] = []

    beforeEach(async () => {
        hub = await createHub()
        personRepository = new PostgresPersonRepository(hub.postgres)
        await resetTestDatabase()
        manager = new PersonsManagerService(hub.personRepository)
        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!

        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
        const result = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '1' },
            {},
            {},
            team.id,
            null,
            true,
            new UUIDT().toString(),
            { distinctId: 'distinct_id_A_1' },
            [{ distinctId: 'distinct_id_A_2' }, { distinctId: 'distinct_id_A_3' }]
        )
        if (!result.success) {
            throw new Error('Failed to create person')
        }
        const person1 = result.person
        const result2 = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '2' },
            {},
            {},
            team.id,
            null,
            true,
            new UUIDT().toString(),
            { distinctId: 'distinct_id_B_1' }
        )
        if (!result2.success) {
            throw new Error('Failed to create person')
        }
        const person2 = result2.person
        const result3 = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '3' },
            {},
            {},
            team2.id,
            null,
            true,
            new UUIDT().toString(),
            { distinctId: 'distinct_id_A_1' }
        )
        if (!result3.success) {
            throw new Error('Failed to create person')
        }
        const person3 = result3.person
        persons = [person1, person2, person3]
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.restoreAllMocks()
    })

    it('returns the persons requested', async () => {
        const res = await Promise.all([
            manager.get({ teamId: team.id, distinctId: 'distinct_id_A_1' }),
            manager.get({ teamId: team.id, distinctId: 'distinct_id_B_1' }),
        ])

        expect(res).toEqual([
            {
                distinct_id: 'distinct_id_A_1',
                id: persons[0].uuid,
                properties: {
                    foo: '1',
                },
                team_id: team.id,
            },
            {
                distinct_id: 'distinct_id_B_1',
                id: persons[1].uuid,
                properties: {
                    foo: '2',
                },
                team_id: team.id,
            },
        ])
    })

    it('returns the different persons for different teams', async () => {
        const res = await Promise.all([
            manager.get({ teamId: team.id, distinctId: 'distinct_id_A_1' }),
            manager.get({ teamId: team2.id, distinctId: 'distinct_id_A_1' }),
        ])

        expect(res).toEqual([
            {
                distinct_id: 'distinct_id_A_1',
                id: persons[0].uuid,
                properties: {
                    foo: '1',
                },
                team_id: team.id,
            },
            {
                distinct_id: 'distinct_id_A_1',
                id: persons[2].uuid,
                properties: {
                    foo: '3',
                },
                team_id: team2.id,
            },
        ])
    })

    it('returns the same person for different distinct ids', async () => {
        const res = await Promise.all([
            manager.get({ teamId: team.id, distinctId: 'distinct_id_A_1' }),
            manager.get({ teamId: team.id, distinctId: 'distinct_id_A_2' }),
        ])

        expect(res).toEqual([
            {
                distinct_id: 'distinct_id_A_1',
                id: persons[0].uuid,
                properties: {
                    foo: '1',
                },
                team_id: team.id,
            },
            {
                distinct_id: 'distinct_id_A_2',
                id: persons[0].uuid,
                properties: {
                    foo: '1',
                },
                team_id: team.id,
            },
        ])
    })

    describe('streamMany', () => {
        it('calls onPerson for each person fetched', async () => {
            const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
            const mockPersons = [
                {
                    id: '1',
                    uuid: 'person-1',
                    distinct_id: 'distinct-1',
                    team_id: team.id,
                    properties: { name: 'Alice' },
                    is_user_id: null,
                    is_identified: true,
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                    created_at: TIMESTAMP,
                    version: 0,
                },
                {
                    id: '2',
                    uuid: 'person-2',
                    distinct_id: 'distinct-2',
                    team_id: team.id,
                    properties: { name: 'Bob' },
                    is_user_id: null,
                    is_identified: true,
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                    created_at: TIMESTAMP,
                    version: 0,
                },
                {
                    id: '3',
                    uuid: 'person-3',
                    distinct_id: 'distinct-3',
                    team_id: team.id,
                    properties: { name: 'Charlie' },
                    is_user_id: null,
                    is_identified: true,
                    properties_last_updated_at: {},
                    properties_last_operation: {},
                    created_at: TIMESTAMP,
                    version: 0,
                },
            ]

            jest.spyOn(hub.personRepository, 'fetchPersonsByProperties').mockResolvedValueOnce(mockPersons)

            const onPerson = jest.fn()
            await manager.streamMany({
                filters: {
                    teamId: team.id,
                    properties: [
                        {
                            type: 'person',
                            key: 'name',
                            operator: PropertyOperator.IsSet,
                            value: 'true',
                        },
                    ],
                },
                onPerson,
            })

            expect(onPerson).toHaveBeenCalledTimes(3)
            expect(onPerson).toHaveBeenNthCalledWith(1, { personId: 'person-1', distinctId: 'distinct-1' })
            expect(onPerson).toHaveBeenNthCalledWith(2, { personId: 'person-2', distinctId: 'distinct-2' })
            expect(onPerson).toHaveBeenNthCalledWith(3, { personId: 'person-3', distinctId: 'distinct-3' })
        })

        it('handles pagination correctly with multiple batches', async () => {
            jest.restoreAllMocks()
            const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
            const batch1 = Array.from({ length: 500 }, (_, i) => ({
                id: `${i}`,
                uuid: `person-${i}`,
                distinct_id: `distinct-${i}`,
                team_id: team.id,
                properties: {},
                is_user_id: null,
                is_identified: true,
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: TIMESTAMP,
                version: 0,
            }))
            const batch2 = Array.from({ length: 300 }, (_, i) => ({
                id: `${i + 500}`,
                uuid: `person-${i + 500}`,
                distinct_id: `distinct-${i + 500}`,
                team_id: team.id,
                properties: {},
                is_user_id: null,
                is_identified: true,
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: TIMESTAMP,
                version: 0,
            }))

            let callCount = 0
            const fetchSpy = jest
                .spyOn(hub.personRepository, 'fetchPersonsByProperties')
                // eslint-disable-next-line @typescript-eslint/require-await
                .mockImplementation(async () => {
                    callCount++
                    return callCount === 1 ? batch1 : batch2
                })

            const onPerson = jest.fn()
            await manager.streamMany({
                filters: { teamId: team.id, properties: [] },
                onPerson,
            })

            expect(fetchSpy).toHaveBeenCalledTimes(2)
            expect(fetchSpy.mock.calls[0][0]).toEqual({
                teamId: team.id,
                properties: [],
                options: { limit: 500, cursor: undefined },
            })
            expect(fetchSpy.mock.calls[1][0]).toEqual({
                teamId: team.id,
                properties: [],
                options: { limit: 500, cursor: '499' },
            })
            expect(onPerson).toHaveBeenCalledTimes(800)
        })

        it('stops paginating when batch is not full', async () => {
            const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
            const batch = Array.from({ length: 200 }, (_, i) => ({
                id: `${i}`,
                uuid: `person-${i}`,
                distinct_id: `distinct-${i}`,
                team_id: team.id,
                properties: {},
                is_user_id: null,
                is_identified: true,
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: TIMESTAMP,
                version: 0,
            }))

            const fetchSpy = jest.spyOn(hub.personRepository, 'fetchPersonsByProperties').mockResolvedValueOnce(batch)

            const onPerson = jest.fn()
            await manager.streamMany({
                filters: { teamId: team.id, properties: [] },
                onPerson,
            })

            expect(fetchSpy).toHaveBeenCalledTimes(1)
            expect(onPerson).toHaveBeenCalledTimes(200)
        })

        it('handles empty results', async () => {
            jest.spyOn(hub.personRepository, 'fetchPersonsByProperties').mockResolvedValueOnce([])

            const onPerson = jest.fn()
            await manager.streamMany({
                filters: { teamId: team.id, properties: [] },
                onPerson,
            })

            expect(onPerson).not.toHaveBeenCalled()
        })

        it('respects custom limit option', async () => {
            const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
            const batch1 = Array.from({ length: 100 }, (_, i) => ({
                id: `${i}`,
                uuid: `person-${i}`,
                distinct_id: `distinct-${i}`,
                team_id: team.id,
                properties: {},
                is_user_id: null,
                is_identified: true,
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: TIMESTAMP,
                version: 0,
            }))
            const batch2 = Array.from({ length: 50 }, (_, i) => ({
                id: `${i + 100}`,
                uuid: `person-${i + 100}`,
                distinct_id: `distinct-${i + 100}`,
                team_id: team.id,
                properties: {},
                is_user_id: null,
                is_identified: true,
                properties_last_updated_at: {},
                properties_last_operation: {},
                created_at: TIMESTAMP,
                version: 0,
            }))

            let callCount = 0
            const fetchSpy = jest
                .spyOn(hub.personRepository, 'fetchPersonsByProperties')
                // eslint-disable-next-line @typescript-eslint/require-await
                .mockImplementation(async () => {
                    callCount++
                    return callCount === 1 ? batch1 : batch2
                })

            const onPerson = jest.fn()
            await manager.streamMany({
                filters: { teamId: team.id, properties: [] },
                options: { limit: 100 },
                onPerson,
            })

            expect(fetchSpy.mock.calls[0][0]).toEqual({
                teamId: team.id,
                properties: [],
                options: { limit: 100, cursor: undefined },
            })
            expect(fetchSpy.mock.calls[1][0]).toEqual({
                teamId: team.id,
                properties: [],
                options: { limit: 100, cursor: '99' },
            })
            expect(onPerson).toHaveBeenCalledTimes(150)
        })
    })
})
