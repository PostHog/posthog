import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { recentQueriesLogic } from './recentQueriesLogic'

describe('recentQueriesLogic', () => {
    let logic: ReturnType<typeof recentQueriesLogic.build>
    let requestedQuery: string
    let requestedValues: Record<string, any>

    beforeEach(() => {
        requestedQuery = ''
        requestedValues = {}
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': async ({ request }) => {
                    const body = (await request.clone().json()) as any
                    requestedQuery = body.query.query
                    requestedValues = body.query.values
                    return [
                        200,
                        {
                            // Column order is the server's to choose, so the mapping must not assume one.
                            columns: ['last_run_at', 'query', 'last_exception_code'],
                            results: [['2026-07-01T10:00:00Z', 'SELECT 1', 0]],
                        },
                    ]
                },
            },
        })
        initKeaTests()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the current user sql editor queries and maps them by column name', async () => {
        logic = recentQueriesLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadRecentQueries', 'loadRecentQueriesSuccess'])

        expect(requestedQuery).toContain('product = {product}')
        expect(requestedQuery).toContain('created_by = {user_id}')
        expect(requestedValues).toMatchObject({ product: 'sql_editor', user_id: MOCK_DEFAULT_USER.id })
        expect(logic.values.recentQueries).toEqual([
            {
                query: 'SELECT 1',
                last_run_at: '2026-07-01T10:00:00Z',
                last_exception_code: 0,
            },
        ])
        expect(logic.values.recentQueriesError).toBeNull()
    })

    it('keeps the error apart from an empty result', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:query_kind/': () => [500, { detail: 'nope' }],
            },
        })

        logic = recentQueriesLogic()
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadRecentQueries', 'loadRecentQueriesFailure'])

        expect(logic.values.recentQueries).toBeNull()
        expect(logic.values.recentQueriesError).toBeTruthy()
    })
})
