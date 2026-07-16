import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { PersonType } from '~/types'

import { searchLogic } from './searchLogic'

describe('searchLogic', () => {
    let logic: ReturnType<typeof searchLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = searchLogic({ logicKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('soft-handles person search failures instead of surfacing a global error toast', async () => {
        // The persons list endpoint runs an expensive ClickHouse ActorsQuery that can time out on
        // large instances. A failure here must resolve to empty results (loader Success) so kea's
        // global onFailure handler never toasts over the user's real work.
        jest.spyOn(api.persons, 'list').mockRejectedValue({ status: 500, detail: 'Query timeout' })

        await expectLogic(logic, () => {
            logic.actions.loadPersonSearchResults({ searchTerm: 'jane' })
        })
            .toDispatchActions(['loadPersonSearchResultsSuccess'])
            .toNotHaveDispatchedActions(['loadPersonSearchResultsFailure'])
            .toMatchValues({ personSearchResults: [] })
    })

    it('returns person results when the search succeeds', async () => {
        const person = { uuid: 'abc', distinct_ids: ['d1'], properties: { email: 'jane@example.com' } } as PersonType
        jest.spyOn(api.persons, 'list').mockResolvedValue({ results: [person], count: 1 })

        await expectLogic(logic, () => {
            logic.actions.loadPersonSearchResults({ searchTerm: 'jane' })
        })
            .toDispatchActions(['loadPersonSearchResultsSuccess'])
            .toMatchValues({ personSearchResults: [person] })
    })
})
