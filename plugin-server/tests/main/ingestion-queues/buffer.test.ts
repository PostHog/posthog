import Piscina from '@posthog/piscina'
import { DateTime } from 'luxon'

import { runBuffer } from '../../../src/main/ingestion-queues/buffer'
import { runInstrumentedFunction } from '../../../src/main/utils'
import { Hub } from '../../../src/types'
import { DB } from '../../../src/utils/db/db'
import { createHub } from '../../../src/utils/db/hub'
import { resetTestDatabase } from '../../helpers/sql'

// jest.mock('../../../src/utils')
jest.mock('../../../src/main/utils')

describe('Event buffer', () => {
    let hub: Hub
    let closeServer: () => Promise<void>
    let db: DB

    beforeEach(async () => {
        ;[hub, closeServer] = await createHub()
        await resetTestDatabase(undefined, {}, {}, { withExtendedTestData: false })
        db = hub.db
    })

    afterEach(async () => {
        await closeServer()
        jest.clearAllMocks()
    })

    describe('runBuffer', () => {
        test('processes events from buffer and deletes them', async () => {
            const processAt = DateTime.now()
            await db.addEventToBuffer({ foo: 'bar' }, processAt)
            await db.addEventToBuffer({ foo: 'bar' }, processAt)

            await runBuffer(hub, {} as Piscina)

            expect(runInstrumentedFunction).toHaveBeenCalledTimes(2)
            expect(runInstrumentedFunction).toHaveBeenLastCalledWith(expect.objectContaining({ event: { foo: 'bar' } }))

            const countResult = await db.postgresQuery(
                'SELECT count(*) FROM posthog_eventbuffer',
                [],
                'eventBufferCountTest'
            )

            expect(Number(countResult.rows[0].count)).toEqual(0)
        })
    })
})
