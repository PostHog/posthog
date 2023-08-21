import { Pool } from 'pg'

import { defaultConfig } from '../../../src/config/config'
import { DependencyUnavailableError } from '../../../src/utils/db/error'
import { assertTablesExist, PostgresRouter, PostgresUse } from '../../../src/utils/db/postgres'
import { personInitialAndUTMProperties } from '../../../src/utils/db/utils'
import { createPostgresPool } from '../../../src/utils/utils'

describe('personInitialAndUTMProperties()', () => {
    it('adds initial and utm properties', () => {
        const properties = {
            distinct_id: 2,
            $browser: 'Chrome',
            $current_url: 'https://test.com',
            $os: 'Mac OS X',
            $browser_version: '95',
            $referring_domain: 'https://google.com',
            $referrer: 'https://google.com/?q=posthog',
            utm_medium: 'twitter',
            gclid: 'GOOGLE ADS ID',
            msclkid: 'BING ADS ID',
            $elements: [
                { tag_name: 'a', nth_child: 1, nth_of_type: 2, attr__class: 'btn btn-sm' },
                { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
            ],
        }

        expect(personInitialAndUTMProperties(properties)).toEqual({
            distinct_id: 2,
            $browser: 'Chrome',
            $current_url: 'https://test.com',
            $os: 'Mac OS X',
            $browser_version: '95',
            $referring_domain: 'https://google.com',
            $referrer: 'https://google.com/?q=posthog',
            utm_medium: 'twitter',
            gclid: 'GOOGLE ADS ID',
            msclkid: 'BING ADS ID',
            $elements: [
                {
                    tag_name: 'a',
                    nth_child: 1,
                    nth_of_type: 2,
                    attr__class: 'btn btn-sm',
                },
                { tag_name: 'div', nth_child: 1, nth_of_type: 2, $el_text: '💻' },
            ],
            $set: { utm_medium: 'twitter', gclid: 'GOOGLE ADS ID', msclkid: 'BING ADS ID' },
            $set_once: {
                $initial_browser: 'Chrome',
                $initial_current_url: 'https://test.com',
                $initial_os: 'Mac OS X',
                $initial_browser_version: '95',
                $initial_utm_medium: 'twitter',
                $initial_gclid: 'GOOGLE ADS ID',
                $initial_msclkid: 'BING ADS ID',
                $initial_referring_domain: 'https://google.com',
                $initial_referrer: 'https://google.com/?q=posthog',
            },
        })
    })

    it('initial current domain regression test', () => {
        const properties = {
            $current_url: 'https://test.com',
        }

        expect(personInitialAndUTMProperties(properties)).toEqual({
            $current_url: 'https://test.com',
            $set_once: { $initial_current_url: 'https://test.com' },
        })
    })
})

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
