import { DateTime } from 'luxon'

import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Person, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'
import { BasePersonRepository } from '~/worker/ingestion/persons/repositories/base-person-repository'

import { PersonsManagerService } from './persons-manager.service'

describe('PersonsManager', () => {
    let hub: Hub
    let personRepository: BasePersonRepository
    let manager: PersonsManagerService
    let team: Team
    let team2: Team
    let persons: Person[] = []

    beforeEach(async () => {
        hub = await createHub()
        personRepository = new BasePersonRepository(hub.db.postgres)
        await resetTestDatabase()
        manager = new PersonsManagerService(hub)
        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!

        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
        const [person1] = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '1' },
            {},
            {},
            team.id,
            null,
            true,
            new UUIDT().toString(),
            [{ distinctId: 'distinct_id_A_1' }, { distinctId: 'distinct_id_A_2' }, { distinctId: 'distinct_id_A_3' }]
        )
        const [person2] = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '2' },
            {},
            {},
            team.id,
            null,
            true,
            new UUIDT().toString(),
            [{ distinctId: 'distinct_id_B_1' }]
        )
        const [person3] = await personRepository.createPerson(
            TIMESTAMP,
            { foo: '3' },
            {},
            {},
            team2.id,
            null,
            true,
            new UUIDT().toString(),
            [{ distinctId: 'distinct_id_A_1' }]
        )

        persons = [person1, person2, person3]
    })

    afterEach(async () => {
        await closeHub(hub)
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
})
