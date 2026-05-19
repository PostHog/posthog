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

    const createPerson = async (
        teamId: number,
        properties: Record<string, any>,
        distinctId: string,
        extraDistinctIds?: string[]
    ): Promise<Person> => {
        const result = await personRepository.createPerson(
            DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC(),
            properties,
            {},
            {},
            teamId,
            null,
            true,
            new UUIDT().toString(),
            { distinctId },
            extraDistinctIds?.map((id) => ({ distinctId: id }))
        )
        if (!result.success) {
            throw new Error('Failed to create person')
        }
        return result.person
    }

    beforeEach(async () => {
        hub = await createHub()
        personRepository = new PostgresPersonRepository(hub.postgres)
        await resetTestDatabase()
        manager = new PersonsManagerService(hub.teamManager, hub.personRepository, 'http://localhost:8000')
        team = await getFirstTeam(hub.postgres)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub.postgres, team2Id))!

        persons = [
            await createPerson(team.id, { foo: '1' }, 'distinct_id_A_1', ['distinct_id_A_2', 'distinct_id_A_3']),
            await createPerson(team.id, { foo: '2' }, 'distinct_id_B_1'),
            await createPerson(team2.id, { foo: '3' }, 'distinct_id_A_1'),
        ]
    })

    afterEach(async () => {
        await closeHub(hub)
        jest.restoreAllMocks()
    })

    describe('getCyclotronPerson with distinct_id', () => {
        it('returns the persons requested', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(team.id, 'distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(team.id, 'distinct_id_B_1', 'distinct_id'),
            ])

            expect(res).toEqual([
                {
                    id: persons[0].uuid,
                    properties: { foo: '1' },
                    name: 'distinct_id_A_1',
                    url: `http://localhost:8000/project/${team.id}/person/distinct_id_A_1`,
                },
                {
                    id: persons[1].uuid,
                    properties: { foo: '2' },
                    name: 'distinct_id_B_1',
                    url: `http://localhost:8000/project/${team.id}/person/distinct_id_B_1`,
                },
            ])
        })

        it('handles distinct IDs containing colons', async () => {
            const person1 = await createPerson(team.id, { foo: '1' }, 'foo:distinct_id_A_1')
            const person2 = await createPerson(team.id, { foo: '2' }, 'foo:bar:distinct_id_B_1')

            const res = await Promise.all([
                manager.getCyclotronPerson(team.id, 'foo:distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(team.id, 'foo:bar:distinct_id_B_1', 'distinct_id'),
            ])

            expect(res).toEqual([
                {
                    id: person1.uuid,
                    properties: { foo: '1' },
                    name: 'foo:distinct_id_A_1',
                    url: `http://localhost:8000/project/${team.id}/person/foo%3Adistinct_id_A_1`,
                },
                {
                    id: person2.uuid,
                    properties: { foo: '2' },
                    name: 'foo:bar:distinct_id_B_1',
                    url: `http://localhost:8000/project/${team.id}/person/foo%3Abar%3Adistinct_id_B_1`,
                },
            ])
        })

        it('returns different persons for different teams', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(team.id, 'distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(team2.id, 'distinct_id_A_1', 'distinct_id'),
            ])

            expect(res).toEqual([
                {
                    id: persons[0].uuid,
                    properties: { foo: '1' },
                    name: 'distinct_id_A_1',
                    url: `http://localhost:8000/project/${team.id}/person/distinct_id_A_1`,
                },
                {
                    id: persons[2].uuid,
                    properties: { foo: '3' },
                    name: 'distinct_id_A_1',
                    url: `http://localhost:8000/project/${team2.id}/person/distinct_id_A_1`,
                },
            ])
        })

        it('returns the same person for different distinct ids', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(team.id, 'distinct_id_A_1', 'distinct_id'),
                manager.getCyclotronPerson(team.id, 'distinct_id_A_2', 'distinct_id'),
            ])

            expect(res![0]!.id).toEqual(res![1]!.id)
            expect(res![0]!.properties).toEqual(res![1]!.properties)
        })

        it('returns undefined when person does not exist', async () => {
            const result = await manager.getCyclotronPerson(team.id, 'nonexistent', 'distinct_id')

            expect(result).toBeNull()
        })

        it('returns undefined when team does not exist', async () => {
            const result = await manager.getCyclotronPerson(99999, 'distinct_id_A_1', 'distinct_id')

            expect(result).toBeNull()
        })

        it('encodes special characters in distinct_id for URL', async () => {
            await createPerson(team.id, {}, 'user@example.com')
            manager.clear()
            const result = await manager.getCyclotronPerson(team.id, 'user@example.com', 'distinct_id')

            expect(result).toBeDefined()
            expect(result!.url).toBe(`http://localhost:8000/project/${team.id}/person/user%40example.com`)
        })
    })

    describe('getCyclotronPerson with person_id', () => {
        it('returns a person by their UUID', async () => {
            const result = await manager.getCyclotronPerson(team.id, persons[0].uuid, 'person_id')

            expect(result).toEqual(
                expect.objectContaining({
                    id: persons[0].uuid,
                    properties: { foo: '1' },
                })
            )
        })

        it('returns undefined for a UUID that does not exist', async () => {
            const result = await manager.getCyclotronPerson(team.id, new UUIDT().toString(), 'person_id')

            expect(result).toBeNull()
        })

        it('returns the correct person for each team when UUIDs differ', async () => {
            const res = await Promise.all([
                manager.getCyclotronPerson(team.id, persons[0].uuid, 'person_id'),
                manager.getCyclotronPerson(team2.id, persons[2].uuid, 'person_id'),
            ])

            expect(res).toEqual([
                expect.objectContaining({ id: persons[0].uuid, properties: { foo: '1' } }),
                expect.objectContaining({ id: persons[2].uuid, properties: { foo: '3' } }),
            ])
        })

        it('returns undefined when queried under the wrong team', async () => {
            const result = await manager.getCyclotronPerson(team2.id, persons[0].uuid, 'person_id')

            expect(result).toBeNull()
        })
    })
})
