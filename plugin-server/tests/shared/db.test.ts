import { DateTime } from 'luxon'

import { Hub, Person, PersonPropertyUpdateOperation, PropertyOperator, Team } from '../../src/types'
import { DB } from '../../src/utils/db/db'
import { createHub } from '../../src/utils/db/hub'
import { UUIDT } from '../../src/utils/utils'
import { ActionManager } from '../../src/worker/ingestion/action-manager'
import { getFirstTeam, resetTestDatabase } from '../helpers/sql'

jest.mock('../../src/utils/status')

describe('DB', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase()
        db = hub.db
    })

    afterEach(async () => {
        await closeServer()
    })

    const TEAM_ID = 2
    const ACTION_ID = 69
    const ACTION_STEP_ID = 913

    test('fetchAllActionsGroupedByTeam', async () => {
        const action = await db.fetchAllActionsGroupedByTeam()

        expect(action).toMatchObject({
            [TEAM_ID]: {
                [ACTION_ID]: {
                    id: ACTION_ID,
                    name: 'Test Action',
                    deleted: false,
                    post_to_slack: true,
                    slack_message_format: '',
                    is_calculating: false,
                    steps: [
                        {
                            id: ACTION_STEP_ID,
                            action_id: ACTION_ID,
                            tag_name: null,
                            text: null,
                            href: null,
                            selector: null,
                            url: null,
                            url_matching: null,
                            name: null,
                            event: null,
                            properties: [
                                { type: 'event', operator: PropertyOperator.Exact, key: 'foo', value: ['bar'] },
                            ],
                        },
                    ],
                },
            },
        })
    })

    async function fetchPersonByPersonId(teamId: number, personId: number): Promise<Person> {
        const selectResult = await db.postgresQuery(
            `SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2`,
            [teamId, personId],
            'fetchPersonByPersonId'
        )

        return selectResult.rows[0]
    }

    describe('createPerson', () => {
        let team: Team
        let person: Person
        const uuid = new UUIDT().toString()
        const distinctId = 'distinct_id1'

        const TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z')

        beforeEach(async () => {
            team = await getFirstTeam(hub)
        })

        test('witout properties', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, team.id, null, false, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)

            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('witout properties indentified true', async () => {
            const person = await db.createPerson(TIMESTAMP, {}, {}, team.id, null, true, uuid, [distinctId])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(true)
            expect(fetched_person.properties).toEqual({})
            expect(fetched_person.properties_last_operation).toEqual({})
            expect(fetched_person.properties_last_updated_at).toEqual({})
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('with properties', async () => {
            const person = await db.createPerson(
                TIMESTAMP,
                { a: 123, b: false },
                { c: 'bbb' },
                team.id,
                null,
                false,
                uuid,
                [distinctId]
            )
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({ a: 123, b: false, c: 'bbb' })
            expect(fetched_person.properties_last_operation).toEqual({
                a: PersonPropertyUpdateOperation.Set,
                b: PersonPropertyUpdateOperation.Set,
                c: PersonPropertyUpdateOperation.SetOnce,
            })
            expect(fetched_person.properties_last_updated_at).toEqual({
                a: TIMESTAMP.toISO(),
                b: TIMESTAMP.toISO(),
                c: TIMESTAMP.toISO(),
            })
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })

        test('with set and set_once for the same key', async () => {
            const person = await db.createPerson(TIMESTAMP, { a: 1 }, { a: 2 }, team.id, null, false, uuid, [
                distinctId,
            ])
            const fetched_person = await fetchPersonByPersonId(team.id, person.id)
            expect(fetched_person.is_identified).toEqual(false)
            expect(fetched_person.properties).toEqual({ a: 1 })
            expect(fetched_person.properties_last_operation).toEqual({ a: PersonPropertyUpdateOperation.Set })
            expect(fetched_person.properties_last_updated_at).toEqual({ a: TIMESTAMP.toISO() })
            expect(fetched_person.uuid).toEqual(uuid)
            expect(fetched_person.team_id).toEqual(team.id)
        })
    })

    describe('fetchGroupTypes() and insertGroupType()', () => {
        it('fetches group types that have been inserted', async () => {
            expect(await db.fetchGroupTypes(2)).toEqual({})
            expect(await db.insertGroupType(2, 'g0', 0)).toEqual(0)
            expect(await db.insertGroupType(2, 'g1', 1)).toEqual(1)
            expect(await db.fetchGroupTypes(2)).toEqual({ g0: 0, g1: 1 })
        })

        it('handles conflicting by index when inserting and limits', async () => {
            expect(await db.insertGroupType(2, 'g0', 0)).toEqual(0)
            expect(await db.insertGroupType(2, 'g1', 0)).toEqual(1)
            expect(await db.insertGroupType(2, 'g2', 0)).toEqual(2)
            expect(await db.insertGroupType(2, 'g3', 1)).toEqual(3)
            expect(await db.insertGroupType(2, 'g4', 0)).toEqual(4)
            expect(await db.insertGroupType(2, 'g5', 0)).toEqual(null)
            expect(await db.insertGroupType(2, 'g6', 0)).toEqual(null)

            expect(await db.fetchGroupTypes(2)).toEqual({ g0: 0, g1: 1, g2: 2, g3: 3, g4: 4 })
        })

        it('handles conflict by name when inserting', async () => {
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual(0)
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual(0)
            expect(await db.insertGroupType(2, 'group_name', 0)).toEqual(0)
            expect(await db.insertGroupType(2, 'foo', 0)).toEqual(1)
            expect(await db.insertGroupType(2, 'foo', 0)).toEqual(1)

            expect(await db.fetchGroupTypes(2)).toEqual({ group_name: 0, foo: 1 })
        })
    })
})
