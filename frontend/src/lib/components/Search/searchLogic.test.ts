import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { searchLogic } from './searchLogic'

describe('searchLogic', () => {
    let logic: ReturnType<typeof searchLogic.build>
    let personSearchSignals: (AbortSignal | undefined)[]

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/search/': { results: [], counts: {} },
                '/api/projects/:team_id/file_system/': { results: [], count: 0 },
            },
        })
        initKeaTests()

        personSearchSignals = []
        // Never resolves — the person search only ends when something aborts it.
        jest.spyOn(api.persons, 'list').mockImplementation((_params, options) => {
            personSearchSignals.push(options?.signal)
            return new Promise((_resolve, reject) => {
                options?.signal?.addEventListener('abort', () => {
                    reject(Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' }))
                })
            })
        })

        logic = searchLogic({ logicKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('aborts the in-flight person search when the term is cleared', async () => {
        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        expect(personSearchSignals).toHaveLength(1)
        expect(personSearchSignals[0]?.aborted).toBe(false)

        await expectLogic(logic, () => logic.actions.setSearch('')).toDispatchActions([
            'loadPersonSearchResultsFailure',
        ])
        expect(personSearchSignals[0]?.aborted).toBe(true)
        expect(logic.values.personSearchResultsLoading).toBe(false)
    })

    it('aborts the previous person search on a new term without clearing the loading state', async () => {
        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])

        await expectLogic(logic, () => logic.actions.setSearch('alice b')).toDispatchActions([
            'loadPersonSearchResults',
        ])
        expect(personSearchSignals).toHaveLength(2)
        expect(personSearchSignals[0]?.aborted).toBe(true)
        expect(personSearchSignals[1]?.aborted).toBe(false)

        // The superseded run must not settle the loader the newer run now owns.
        await expectLogic(logic).toNotHaveDispatchedActions(['loadPersonSearchResultsFailure'])
        expect(logic.values.personSearchResultsLoading).toBe(true)
    })
})
