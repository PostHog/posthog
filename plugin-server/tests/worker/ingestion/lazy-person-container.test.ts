import { DateTime } from 'luxon'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { LazyPersonContainer } from '../../../src/worker/ingestion/lazy-person-container'
import { resetTestDatabase } from '../../helpers/sql'

jest.mock('../../../src/utils/status')

const timestamp = DateTime.fromISO('2020-01-01T12:00:05.200Z').toUTC()
const uuid = new UUIDT()

describe('LazyPersonContainer()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>
    let personContainer: LazyPersonContainer

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        await resetTestDatabase()
        personContainer = new LazyPersonContainer(2, 'my-id', hub)

        jest.spyOn(hub.db, 'fetchPerson')
    })

    afterEach(async () => {
        await closeHub()
    })

    it('.get returns undefined if person does not exist', async () => {
        const persons = await Promise.all([personContainer.get(), personContainer.get(), personContainer.get()])

        expect(persons).toEqual([undefined, undefined, undefined])
        expect(personContainer.loaded).toEqual(false)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
    })

    it('.get loads person lazily and once', async () => {
        const person = await hub.db.createPerson(timestamp, {}, 2, null, false, uuid.toString(), ['my-id'])

        const persons = await Promise.all([personContainer.get(), personContainer.get(), personContainer.get()])

        expect(persons).toEqual([person, person, person])
        expect(personContainer.loaded).toEqual(true)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(1)
    })

    it('does not load anything if .with followed by .get', async () => {
        const person = await hub.db.createPerson(timestamp, {}, 2, null, false, uuid.toString(), ['my-id'])
        personContainer = personContainer.with(person)

        const persons = await Promise.all([personContainer.get(), personContainer.get(), personContainer.get()])

        expect(persons).toEqual([person, person, person])
        expect(personContainer.loaded).toEqual(true)
        expect(hub.db.fetchPerson).toHaveBeenCalledTimes(0)
    })
})
