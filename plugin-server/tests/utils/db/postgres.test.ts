import { Pool } from 'pg'

import { defaultConfig } from '../../../src/config/config'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { assertTablesExist, PostgresRouter, PostgresUse } from '../../../src/utils/db/postgres'
import { createPostgresPool } from '../../../src/utils/utils'

describe('PostgresRouter()', () => {
    test('throws DependencyUnavailableError on postgres errors', async () => {
        const errorMessage =
            'connection to server at "posthog-pgbouncer" (171.20.65.128), port 6543 failed: server closed the connection unexpectedly'
        const pgQueryMock = jest.spyOn(Pool.prototype, 'query').mockImplementation(() => {
            return Promise.reject(new Error(errorMessage))
        })

        const router = new PostgresRouter(defaultConfig, null)
        await expect(router.query(PostgresUse.COMMON_WRITE, 'SELECT 1;', null, 'testing')).rejects.toEqual(
            new DependencyUnavailableError(errorMessage, 'Postgres', new Error(errorMessage))
        )
        pgQueryMock.mockRestore()
    })
})

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
