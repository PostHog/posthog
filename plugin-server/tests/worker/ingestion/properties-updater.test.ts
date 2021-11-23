import { Properties } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { Group, Hub, Person, Team } from '../../../src/types'
import { DB } from '../../../src/utils/db/db'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import {
    updatePersonProperties as originalUpdatePersonProperties,
    upsertGroup,
} from '../../../src/worker/ingestion/properties-updater'
import { createPromise } from '../../helpers/promises'
import { getFirstTeam, resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

let hub: Hub
let closeServer: () => Promise<void>
let db: DB

let team: Team
let person: Person
const uuid = new UUIDT().toString()
const distinctId = 'distinct_id_update_person_properties'

const FUTURE_TIMESTAMP = DateTime.fromISO('2050-10-14T11:42:06.502Z')
const MIDDLE_TIMESTAMP = DateTime.fromISO('2021-10-14T11:42:06.502Z')
const PAST_TIMESTAMP = DateTime.fromISO('2000-10-14T11:42:06.502Z')

beforeEach(async () => {
    ;[hub, closeServer] = await createHub()
    await resetTestDatabase()
    db = hub.db

    team = await getFirstTeam(hub)
    person = await db.createPerson(PAST_TIMESTAMP, {}, {}, team.id, null, false, uuid, [distinctId])
})

afterEach(async () => {
    await closeServer()
})

describe('updatePersonProperties()', () => {
    //  How we expect this query to behave:
    //    | value exists | method   | previous method | previous TS is ___ call TS | write/override
    //  1 | no           | N/A      | N/A             | N/A                        | yes
    //  2 | yes          | set      | set             | before                     | yes
    //  3 | yes          | set_once | set             | before                     | no
    //  4 | yes          | set      | set_once        | before                     | yes
    //  5 | yes          | set_once | set_once        | before                     | no
    //  6 | yes          | set      | set             | equal                      | no
    //  7 | yes          | set_once | set             | equal                      | no
    //  8 | yes          | set      | set_once        | equal                      | yes
    //  9 | yes          | set_once | set_once        | equal                      | no
    // 10 | yes          | set      | set             | after                      | no
    // 11 | yes          | set_once | set             | after                      | no
    // 12 | yes          | set      | set_once        | after                      | yes
    // 13 | yes          | set_once | set_once        | after                      | yes

    // util to get the new props after an update
    async function updatePersonProperties(
        properties: Properties,
        propertiesOnce: Properties,
        timestamp: DateTime
    ): Promise<Person['properties'] | undefined> {
        await originalUpdatePersonProperties(db, team.id, distinctId, properties, propertiesOnce, timestamp)
        return (await fetchPersonByPersonId(team.id, person.id)).properties
    }

    async function fetchPersonByPersonId(teamId: number, personId: number): Promise<Person> {
        const selectResult = await db.postgresQuery(
            `SELECT * FROM posthog_person WHERE team_id = $1 AND id = $2`,
            [teamId, personId],
            'fetchPersonByPersonId'
        )

        return selectResult.rows[0]
    }

    it('handles empty properties', async () => {
        const props = await updatePersonProperties({}, {}, PAST_TIMESTAMP)
        expect(props).toEqual({})
    })

    it('handles non-existent single property', async () => {
        const props = await updatePersonProperties({ a: 'a' }, {}, PAST_TIMESTAMP)
        expect(props).toEqual({ a: 'a' })
    })

    it('handles non-existent property', async () => {
        const props = await updatePersonProperties({ a: 'a' }, { b: 'b' }, PAST_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
    })

    it('handles set and set once same key', async () => {
        const props = await updatePersonProperties({ a: 'a set' }, { a: 'a set_once' }, PAST_TIMESTAMP)
        expect(props).toEqual({ a: 'a set' })
    })

    it('handles prop with newer timestamp - rows [2-5]', async () => {
        // setup initially lower case letters
        let props = await updatePersonProperties({ r2: 'a', r3: 'b' }, { r4: 'c', r5: 'd' }, PAST_TIMESTAMP)
        expect(props).toEqual({ r2: 'a', r3: 'b', r4: 'c', r5: 'd' })
        // update to upper case letters
        props = await updatePersonProperties({ r2: 'A', r4: 'C' }, { r3: 'B', r5: 'D' }, FUTURE_TIMESTAMP)
        expect(props).toEqual({ r2: 'A', r3: 'b', r4: 'C', r5: 'd' })
    })

    it('handles prop with equal timestamp - rows [6-9] ', async () => {
        // setup initially lower case letters
        let props = await updatePersonProperties({ r6: 'a', r7: 'b' }, { r8: 'c', r9: 'd' }, PAST_TIMESTAMP)
        expect(props).toEqual({ r6: 'a', r7: 'b', r8: 'c', r9: 'd' })
        // update to upper case letters
        props = await updatePersonProperties({ r6: 'A', r8: 'C' }, { r7: 'B', r9: 'D' }, PAST_TIMESTAMP)
        expect(props).toEqual({ r6: 'a', r7: 'b', r8: 'C', r9: 'd' })
    })

    it('handles prop with older timestamp - rows [10-13] ', async () => {
        // setup initially lower case letters
        let props = await updatePersonProperties({ r10: 'a', r11: 'b' }, { r12: 'c', r13: 'd' }, FUTURE_TIMESTAMP)
        expect(props).toEqual({ r10: 'a', r11: 'b', r12: 'c', r13: 'd' })
        // update to upper case letters
        props = await updatePersonProperties({ r10: 'A', r12: 'C' }, { r11: 'B', r13: 'D' }, PAST_TIMESTAMP)
        expect(props).toEqual({ r10: 'a', r11: 'b', r12: 'C', r13: 'D' })
    })
    it('updates timestamps when newer timestamp equal values for set op', async () => {
        // set initial properties
        let props = await updatePersonProperties({ a: 'a' }, { b: 'b' }, PAST_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
        // no-value change with future timestamp
        props = await updatePersonProperties({ a: 'a' }, { b: 'b' }, FUTURE_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
        // value change with middle timestamp is ignored
        props = await updatePersonProperties({ a: 'aaaa' }, { b: 'bbbb' }, MIDDLE_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
    })

    it('updates timestamps when newer timestamp equal values for set_once', async () => {
        // set initial properties
        let props = await updatePersonProperties({ a: 'a' }, { b: 'b' }, FUTURE_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
        // no-value change with past timestamp
        props = await updatePersonProperties({ a: 'a' }, { b: 'b' }, PAST_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
        // value change with middle timestamp is ignored
        props = await updatePersonProperties({ a: 'aaaa' }, { b: 'bbbb' }, MIDDLE_TIMESTAMP)
        expect(props).toEqual({ a: 'a', b: 'b' })
    })

    // TODO test that we can't change the person in the middle of the update
})

describe('upsertGroup()', () => {
    async function upsert(properties: Properties, timestamp: DateTime) {
        await upsertGroup(hub.db, team.id, 0, 'group_key', properties, timestamp)
    }

    async function fetchGroup(): Promise<Group> {
        return (await hub.db.fetchGroup(team.id, 0, 'group_key'))!
    }

    it('creates a row if one does not yet exist with empty properties', async () => {
        await upsert({}, PAST_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(1)
        expect(group.group_properties).toEqual({})
        expect(group.properties_last_operation).toEqual({})
        expect(group.properties_last_updated_at).toEqual({})
    })

    it('handles initial properties', async () => {
        await upsert({ foo: 'bar' }, PAST_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(1)
        expect(group.group_properties).toEqual({ foo: 'bar' })
        expect(group.properties_last_operation).toEqual({ foo: 'set' })
        expect(group.properties_last_updated_at).toEqual({ foo: PAST_TIMESTAMP.toISO() })
    })

    it('handles updating properties as new ones come in', async () => {
        await upsert({ foo: 'bar', a: 1 }, PAST_TIMESTAMP)
        await upsert({ foo: 'zeta', b: 2 }, FUTURE_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(2)
        expect(group.group_properties).toEqual({ foo: 'zeta', a: 1, b: 2 })
        expect(group.properties_last_operation).toEqual({ foo: 'set', a: 'set', b: 'set' })
        expect(group.properties_last_updated_at).toEqual({
            foo: FUTURE_TIMESTAMP.toISO(),
            a: PAST_TIMESTAMP.toISO(),
            b: FUTURE_TIMESTAMP.toISO(),
        })
    })

    it('handles updating when processing old events', async () => {
        await upsert({ foo: 'bar', a: 1 }, FUTURE_TIMESTAMP)
        await upsert({ foo: 'zeta', b: 2 }, PAST_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(2)
        expect(group.group_properties).toEqual({ foo: 'bar', a: 1, b: 2 })
        expect(group.properties_last_operation).toEqual({ foo: 'set', a: 'set', b: 'set' })
        expect(group.properties_last_updated_at).toEqual({
            foo: FUTURE_TIMESTAMP.toISO(),
            a: FUTURE_TIMESTAMP.toISO(),
            b: PAST_TIMESTAMP.toISO(),
        })
    })

    it('updates timestamp even if properties do not change', async () => {
        await upsert({ foo: 'bar' }, PAST_TIMESTAMP)
        await upsert({ foo: 'bar' }, FUTURE_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(2)
        expect(group.group_properties).toEqual({ foo: 'bar' })
        expect(group.properties_last_operation).toEqual({ foo: 'set' })
        expect(group.properties_last_updated_at).toEqual({ foo: FUTURE_TIMESTAMP.toISO() })
    })

    it('does nothing if handling equal timestamps', async () => {
        await upsert({ foo: '1' }, PAST_TIMESTAMP)
        await upsert({ foo: '2' }, PAST_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(1)
        expect(group.group_properties).toEqual({ foo: '1' })
        expect(group.properties_last_operation).toEqual({ foo: 'set' })
        expect(group.properties_last_updated_at).toEqual({ foo: PAST_TIMESTAMP.toISO() })
    })

    it('does nothing if nothing gets updated due to timestamps', async () => {
        await upsert({ foo: 'new' }, FUTURE_TIMESTAMP)
        await upsert({ foo: 'old' }, PAST_TIMESTAMP)

        const group = await fetchGroup()

        expect(group.version).toEqual(1)
        expect(group.group_properties).toEqual({ foo: 'new' })
        expect(group.properties_last_operation).toEqual({ foo: 'set' })
        expect(group.properties_last_updated_at).toEqual({ foo: FUTURE_TIMESTAMP.toISO() })
    })

    it('handles race conditions as inserts happen in parallel', async () => {
        // :TRICKY: This test is closely coupled with the method under test and we
        //  control the timing of functions called precisely to emulate a race condition

        const firstFetchIsDonePromise = createPromise()
        const firstInsertShouldStartPromise = createPromise()

        jest.spyOn(db, 'insertGroup').mockImplementationOnce(async (...args) => {
            firstFetchIsDonePromise.resolve()
            await firstInsertShouldStartPromise.promise
            return await db.insertGroup(...args)
        })

        // First, we start first update, and wait until first fetch is done (and returns that group does not exist)
        const firstUpsertPromise = upsert({ a: 1, b: 2 }, PAST_TIMESTAMP)
        await firstFetchIsDonePromise.promise

        // Second, we do a another (complete) upsert in-between which creates a row in groups table
        await upsert({ a: 3 }, FUTURE_TIMESTAMP)

        // Third, we continue with the original upsert, and wait for the end
        firstInsertShouldStartPromise.resolve()
        await firstUpsertPromise

        // Verify the results
        const group = await fetchGroup()
        expect(group.version).toEqual(2)
        expect(group.group_properties).toEqual({ a: 3, b: 2 })
        expect(group.properties_last_operation).toEqual({ a: 'set', b: 'set' })
        expect(group.properties_last_updated_at).toEqual({ a: FUTURE_TIMESTAMP.toISO(), b: PAST_TIMESTAMP.toISO() })
    })
})
