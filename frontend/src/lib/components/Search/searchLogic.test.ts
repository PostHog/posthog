import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { searchLogic } from './searchLogic'

describe('searchLogic', () => {
    let logic: ReturnType<typeof searchLogic.build>
    let personSearchCalls: { clientQueryId?: string; signal?: AbortSignal }[]
    let cancelledQueryIds: string[]
    let personListMock: jest.SpyInstance

    const neverResolvingPersonSearch = (): void => {
        personListMock.mockImplementation((params, options) => {
            personSearchCalls.push({ clientQueryId: params?.client_query_id, signal: options?.signal })
            return new Promise((_resolve, reject) => {
                options?.signal?.addEventListener('abort', () => {
                    reject(Object.assign(new Error('The user aborted a request.'), { name: 'AbortError' }))
                })
            })
        })
    }

    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/search/': { results: [], counts: {} },
                '/api/projects/:team_id/file_system/': { results: [], count: 0 },
            },
        })
        initKeaTests()

        personSearchCalls = []
        cancelledQueryIds = []
        personListMock = jest.spyOn(api.persons, 'list')
        jest.spyOn(api, 'cancelQuery').mockImplementation(async (clientQueryId: string) => {
            cancelledQueryIds.push(clientQueryId)
        })

        logic = searchLogic({ logicKey: 'test' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('aborts and cancels the in-flight person search when the term is cleared', async () => {
        neverResolvingPersonSearch()

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        expect(personSearchCalls).toHaveLength(1)
        const { clientQueryId, signal } = personSearchCalls[0]
        expect(clientQueryId).toBeTruthy()
        expect(signal?.aborted).toBe(false)

        await expectLogic(logic, () => logic.actions.setSearch('')).toDispatchActions([
            'loadPersonSearchResultsFailure',
        ])
        expect(signal?.aborted).toBe(true)
        expect(cancelledQueryIds).toEqual([clientQueryId])
        expect(logic.values.personSearchResultsLoading).toBe(false)
    })

    it('cancels the previous person search on a new term without clearing the loading state', async () => {
        neverResolvingPersonSearch()

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions(['loadPersonSearchResults'])
        await expectLogic(logic, () => logic.actions.setSearch('alice b')).toDispatchActions([
            'loadPersonSearchResults',
        ])

        expect(personSearchCalls).toHaveLength(2)
        expect(personSearchCalls[0].signal?.aborted).toBe(true)
        expect(personSearchCalls[1].signal?.aborted).toBe(false)
        expect(cancelledQueryIds).toEqual([personSearchCalls[0].clientQueryId])

        // The superseded run must not settle the loader the newer run now owns.
        await expectLogic(logic).toNotHaveDispatchedActions(['loadPersonSearchResultsFailure'])
        expect(logic.values.personSearchResultsLoading).toBe(true)
    })

    it('does not cancel a person search that already returned', async () => {
        personListMock.mockResolvedValue({ results: [] })

        await expectLogic(logic, () => logic.actions.setSearch('alice')).toDispatchActions([
            'loadPersonSearchResultsSuccess',
        ])
        await expectLogic(logic, () => logic.actions.setSearch('')).toFinishAllListeners()

        expect(cancelledQueryIds).toEqual([])
    })
})
