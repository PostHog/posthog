import { DateTime } from 'luxon'

import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Person, Team } from '~/types'
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
        team = await getFirstTeam(hub.postgres)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub.postgres, team2Id))!

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
            manager.get({ teamId: team.id, id: 'distinct_id_A_1' }),
            manager.get({ teamId: team.id, id: 'distinct_id_B_1' }),
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

    it('returns the persons requested when distinct IDs contain colons', async () => {
        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
        const result1 = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '1' },
            {},
            {},
            team.id,
            null,
            true,
            new UUIDT().toString(),
            { distinctId: 'foo:distinct_id_A_1' }
        )
        if (!result1.success) {
            throw new Error('Failed to create person')
        }
        const person1 = result1.person
        const result2 = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '2' },
            {},
            {},
            team.id,
            null,
            true,
            new UUIDT().toString(),
            { distinctId: 'foo:bar:distinct_id_B_1' }
        )
        if (!result2.success) {
            throw new Error('Failed to create person')
        }
        const person2 = result2.person

        const res = await Promise.all([
            manager.get({ teamId: team.id, id: 'foo:distinct_id_A_1' }),
            manager.get({ teamId: team.id, id: 'foo:bar:distinct_id_B_1' }),
        ])

        expect(res).toEqual([
            {
                distinct_id: 'foo:distinct_id_A_1',
                id: person1.uuid,
                properties: {
                    foo: '1',
                },
                team_id: team.id,
            },
            {
                distinct_id: 'foo:bar:distinct_id_B_1',
                id: person2.uuid,
                properties: {
                    foo: '2',
                },
                team_id: team.id,
            },
        ])
    })

    it('returns the different persons for different teams', async () => {
        const res = await Promise.all([
            manager.get({ teamId: team.id, id: 'distinct_id_A_1' }),
            manager.get({ teamId: team2.id, id: 'distinct_id_A_1' }),
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
            manager.get({ teamId: team.id, id: 'distinct_id_A_1' }),
            manager.get({ teamId: team.id, id: 'distinct_id_A_2' }),
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

    describe('person_id lookup mode', () => {
        let personIdManager: PersonsManagerService

        beforeEach(() => {
            personIdManager = new PersonsManagerService(hub.personRepository, 'person_id')
        })

        it('returns a person by their UUID', async () => {
            const result = await personIdManager.get({ teamId: team.id, id: persons[0].uuid })

            expect(result).toEqual({
                id: persons[0].uuid,
                properties: { foo: '1' },
                team_id: team.id,
            })
        })

        it('returns null for a UUID that does not exist', async () => {
            const result = await personIdManager.get({ teamId: team.id, id: new UUIDT().toString() })

            expect(result).toBeNull()
        })

        it('returns the correct person for each team when UUIDs differ', async () => {
            const res = await Promise.all([
                personIdManager.get({ teamId: team.id, id: persons[0].uuid }),
                personIdManager.get({ teamId: team2.id, id: persons[2].uuid }),
            ])

            expect(res).toEqual([
                { id: persons[0].uuid, properties: { foo: '1' }, team_id: team.id },
                { id: persons[2].uuid, properties: { foo: '3' }, team_id: team2.id },
            ])
        })

        it('does not return a person when queried under the wrong team', async () => {
            const result = await personIdManager.get({ teamId: team2.id, id: persons[0].uuid })

            expect(result).toBeNull()
        })
    })
})
