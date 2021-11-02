import { DateTime } from 'luxon'

import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { UUIDT } from '../../../src/utils/utils'
import { PersonManager } from '../../../src/worker/ingestion/person-manager'
import { resetTestDatabase } from '../../helpers/sql'

describe('PersonManager.isNewPerson', () => {
    let personManager: PersonManager
    let hub: Hub
    let closeHub: () => Promise<void>

    const check = (distinctId: string) => personManager.isNewPerson(hub.db, 2, distinctId)
    const createPerson = async (distinctId: string) => {
        const uuid = new UUIDT().toString()
        await hub.db.createPerson(DateTime.utc(), {}, 2, null, false, uuid, [distinctId])
    }

    beforeEach(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub({
            DISTINCT_ID_LRU_SIZE: 10,
        })
        personManager = new PersonManager(hub)
    })

    afterEach(async () => {
        await closeHub()
    })

    it('returns whether person exists or not', async () => {
        await createPerson('1234')

        expect(await check('1234')).toEqual(false)
        expect(await check('12345')).toEqual(true)
        expect(await check('567')).toEqual(true)
        expect(await check('567')).toEqual(false)
    })

    it('keeps a cache', async () => {
        await createPerson('1234')
        await createPerson('567')

        const spy = jest.spyOn(hub.db, 'postgresQuery')

        expect(await check('1234')).toEqual(false)
        expect(await check('567')).toEqual(false)
        expect(await check('1234')).toEqual(false)
        expect(await check('1234')).toEqual(false)
        expect(await check('1234')).toEqual(false)
        expect(await check('new-id')).toEqual(true)
        expect(await check('new-id')).toEqual(false)

        expect(spy).toHaveBeenCalledTimes(3)
    })
})
