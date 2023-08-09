import { Hub } from '../../../src/types'
import { createHub } from '../../../src/utils/db/hub'
import { assertTablesExist } from '../../../src/utils/db/postgres'
import { resetTestDatabase } from '../../helpers/sql'

describe('assertTablesExist()', () => {
    let hub: Hub
    let closeHub: () => Promise<void>

    beforeAll(async () => {
        await resetTestDatabase()
        ;[hub, closeHub] = await createHub({})
    })

    afterAll(async () => {
        await closeHub()
    })

    it('succeeds if all tables exist', async () => {
        await assertTablesExist(hub.db.postgres, ['posthog_pluginconfig', 'posthog_team'])
    })

    it('succeeds if one table is missing', async () => {
        await expect(
            assertTablesExist(hub.db.postgres, ['posthog_pluginconfig', 'not_found1', 'not_found2'])
        ).rejects.toEqual(new Error('Configured PG target does not hold the expected tables: not_found1, not_found2'))
    })
})
