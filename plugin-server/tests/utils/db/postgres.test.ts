import { Pool } from 'pg'

import { defaultConfig } from '../../../src/config/config'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { PostgresRouter, PostgresUse } from '../../../src/utils/db/postgres'

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
