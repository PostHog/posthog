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

    it('requests the first page with the default ordering and no filters', () => {
        const params = parseParams(logic.values.apiParams)
        expect(params.get('limit')).toEqual('50')
        expect(params.get('offset')).toEqual('0')
        expect(params.get('ordering')).toEqual('-created_by')
        expect(params.get('search')).toBeNull()
        expect(params.get('created_by')).toBeNull()
        expect(params.get('tags')).toBeNull()
    })

    it('sends tags as a JSON-encoded array so the backend can filter by tag name', () => {
        logic.actions.setFilters({ tags: ['billing', 'beta'] })
        expect(parseParams(logic.values.apiParams).get('tags')).toEqual(JSON.stringify(['billing', 'beta']))
    })

    it('sends selected creator ids as a comma-separated list', () => {
        logic.actions.setFilters({ createdBy: [3, 7] })
        expect(parseParams(logic.values.apiParams).get('created_by')).toEqual('3,7')
    })

    it('translates page navigation into the right offset', () => {
        logic.actions.setPage(3)
        expect(parseParams(logic.values.apiParams).get('offset')).toEqual('100')
    })

    it('resets to the first page when a filter changes, so no page shows a stale offset', () => {
        logic.actions.setPage(3)
        logic.actions.setFilters({ tags: ['billing'] })
        expect(logic.values.page).toEqual(1)
        expect(parseParams(logic.values.apiParams).get('offset')).toEqual('0')
    })
})
