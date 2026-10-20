jest.unmock('lib/utils/concurrencyController')

import { expectLogic } from 'kea-test-utils'

import { promiseResolveReject } from 'lib/utils/async'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { AccountsTableQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query', () => ({
    __esModules: true,
    ...jest.requireActual('~/queries/query'),
    performQuery: jest.fn(),
}))

const mockedQuery = performQuery as jest.MockedFunction<typeof performQuery>

describe('dataNodeLogic concurrency', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('starts two account table queries before starting a third', async () => {
        const pendingResponses = [
            promiseResolveReject<AccountsTableQueryResponse>(),
            promiseResolveReject<AccountsTableQueryResponse>(),
            promiseResolveReject<AccountsTableQueryResponse>(),
        ]
        const thirdQueryStarted = promiseResolveReject<void>()
        let nextResponse = 0
        mockedQuery.mockImplementation(() => {
            const pendingResponse = pendingResponses[nextResponse++]
            if (nextResponse === 3) {
                thirdQueryStarted.resolve()
            }
            return pendingResponse.promise
        })

        const logics = ['rows', 'overview', 'totals'].map((key) =>
            dataNodeLogic({
                key: `accounts-${key}`,
                query: { kind: NodeKind.AccountsTableQuery, columns: [], filters: [] },
            })
        )

        try {
            logics.forEach((logic) => logic.mount())

            expect(mockedQuery).toHaveBeenCalledTimes(2)

            pendingResponses[0].resolve({
                kind: NodeKind.AccountsTableQuery,
                results: [],
                hasMore: false,
                limit: 100,
                offset: 0,
            })
            await thirdQueryStarted.promise
            expect(mockedQuery).toHaveBeenCalledTimes(3)
        } finally {
            pendingResponses.forEach(({ resolve }) =>
                resolve({ kind: NodeKind.AccountsTableQuery, results: [], hasMore: false, limit: 100, offset: 0 })
            )
            await Promise.all(logics.map((logic) => expectLogic(logic).toFinishAllListeners()))
            logics.forEach((logic) => logic.unmount())
        }
    })
})
