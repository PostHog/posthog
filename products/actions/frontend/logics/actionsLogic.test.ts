import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

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

    // Pin only changes pinned_at. Echoing name back re-runs name validation, so an action
    // with a blank name (which the model allows) fails to pin with "This field may not be blank".
    it.each([
        ['pinAction', 'pinActionSuccess'],
        ['unpinAction', 'unpinActionSuccess'],
    ])('%s sends only pinned_at, never name', async (actionName, successAction) => {
        const blankNameAction = { id: 7, name: '', steps: [], pinned_at: null }
        let patchedBody: Record<string, any> | undefined
        useMocks({
            get: {
                '/api/projects/:team/actions/': { count: 1, results: [blankNameAction] },
            },
            patch: {
                '/api/projects/:team/actions/:id/': async ({ request }) => {
                    patchedBody = (await request.json()) as Record<string, any>
                    return [200, { ...blankNameAction, ...patchedBody }]
                },
            },
        })

        await expectLogic(logic, () => {
            logic.actions[actionName as 'pinAction' | 'unpinAction'](blankNameAction as any)
        }).toDispatchActions([successAction])

        expect(patchedBody).not.toHaveProperty('name')
        expect(patchedBody).toHaveProperty('pinned_at')
    })
})
