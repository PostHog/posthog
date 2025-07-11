import { DateTime } from 'luxon'

import { forSnapshot } from '~/tests/helpers/snapshots'
import { createTeam, getFirstTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Person, Team } from '~/types'
import { closeHub, createHub } from '~/utils/db/hub'
import { UUIDT } from '~/utils/utils'

import { insertHogFunctionTemplate } from '../../_tests/fixtures'
import { compileHog } from '../../templates/compiler'
import { HogFunctionTemplateManagerService } from './hog-function-template-manager.service'
import { PersonsManagerService } from './persons-manager.service'

describe('PersonsManager', () => {
    let hub: Hub
    let manager: PersonsManagerService
    let hogFunctionsTemplates: Person[]
    let team: Team
    let team2: Team
    let persons: Person[] = []

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        manager = new PersonsManagerService(hub)
        team = await getFirstTeam(hub)
        const team2Id = await createTeam(hub.postgres, team.organization_id)
        team2 = (await getTeam(hub, team2Id))!
        hogFunctionsTemplates = []

        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z').toUTC()
        const uuid = new UUIDT().toString()
        const [person1] = await hub.db.createPerson(TIMESTAMP, { foo: '1' }, {}, {}, team.id, null, true, uuid, [
            { distinctId: 'distinct_id_1' },
        ])
        const [person2] = await hub.db.createPerson(TIMESTAMP, { foo: '2' }, {}, {}, team.id, null, true, uuid, [
            { distinctId: 'distinct_id_2' },
        ])

        persons = [person1, person2]
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('returns the persons requested', async () => {
        const res = await Promise.all([
            manager.get({ teamId: team.id, distinctId: 'distinct_id_1' }),
            manager.get({ teamId: team.id, distinctId: 'distinct_id_2' }),
        ])

        expect(res).toEqual([
            {
                distinct_id: 'distinct_id_1',
                id: persons[0].uuid,
                properties: {
                    foo: '1',
                },
                team_id: 2,
            },
            {
                distinct_id: 'distinct_id_2',
                id: persons[1].uuid,
                properties: {
                    foo: '2',
                },
                team_id: 2,
            },
        ])
    })
})
