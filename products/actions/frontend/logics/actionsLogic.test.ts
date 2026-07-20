import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { actionsLogic } from './actionsLogic'

const parseParams = (query: string): URLSearchParams => new URLSearchParams(query)

describe('actionsLogic', () => {
    let logic: ReturnType<typeof actionsLogic.build>

    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = { current_user: MOCK_DEFAULT_USER } as unknown as AppContext

        useMocks({
            get: {
                '/api/projects/:team/actions/': { count: 0, results: [] },
            },
        })

        initKeaTests()
        logic = actionsLogic()
        logic.mount()
    })

    // apiParams is the contract with the backend list endpoint, so lock the mapping from
    // filter state to query string: wrong tag/creator encoding or offset math breaks filtering.
    it.each([
        ['default page and ordering', () => {}, { limit: '50', offset: '0', ordering: '-created_by' }],
        [
            'tags as a JSON-encoded array',
            (l: typeof logic) => l.actions.setFilters({ tags: ['billing', 'beta'] }),
            { tags: JSON.stringify(['billing', 'beta']) },
        ],
        [
            'creator ids as a comma-separated list',
            (l: typeof logic) => l.actions.setFilters({ createdBy: [3, 7] }),
            { created_by: '3,7' },
        ],
        ['page navigation as an offset', (l: typeof logic) => l.actions.setPage(3), { offset: '100' }],
    ])('sends %s', (_name, setup, expected) => {
        setup(logic)
        const params = Object.fromEntries(parseParams(logic.values.apiParams))
        expect(params).toMatchObject(expected)
    })

    it('resets to the first page when a filter changes, so no page shows a stale offset', () => {
        logic.actions.setPage(3)
        logic.actions.setFilters({ tags: ['billing'] })
        expect(logic.values.page).toEqual(1)
        expect(parseParams(logic.values.apiParams).get('offset')).toEqual('0')
    })
})
