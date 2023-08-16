import { Pool } from 'pg'

import { defaultConfig } from '../../../src/config/config'
import { assertTablesExist } from '../../../src/utils/db/postgres'
import { createPostgresPool } from '../../../src/utils/utils'

describe('assertTablesExist()', () => {
    let client: Pool

    beforeAll(() => {
        client = createPostgresPool(defaultConfig.DATABASE_URL, defaultConfig.POSTGRES_CONNECTION_POOL_SIZE)
    })

    afterAll(async () => {
        await client.end()
    })

    it('succeeds if all tables exist', async () => {
        await assertTablesExist(client, ['posthog_pluginconfig', 'posthog_team'])
    })

    it('succeeds if one table is missing', async () => {
        await expect(assertTablesExist(client, ['posthog_pluginconfig', 'not_found1', 'not_found2'])).rejects.toEqual(
            new Error('Configured PG target does not hold the expected tables: not_found1, not_found2')
        )
    })
})
