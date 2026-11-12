jest.unmock('lib/utils/concurrencyController')

import { expectLogic } from 'kea-test-utils'

import { promiseResolveReject } from 'lib/utils/async'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { AccountsTableQueryResponse, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
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

    it.each([
        { scene: Scene.SavedInsights, limit: 6 },
        { scene: Scene.AnalyticsProductHome, limit: 6 },
        { scene: Scene.Max, limit: 4 },
        { scene: Scene.Insight, limit: 1 },
    ])('runs at most $limit queries at once in $scene', async ({ scene, limit }) => {
        sceneLogic.mount()
        sceneLogic.actions.setScene(scene, undefined, { params: {}, searchParams: {}, hashParams: {} })
        const response: HogQLQueryResponse = { results: [], columns: [], types: [] }
        const pendingResponses = Array.from({ length: limit + 1 }, () => promiseResolveReject<HogQLQueryResponse>())
        const nextQueryStarted = promiseResolveReject<void>()
        let nextResponse = 0
        mockedQuery.mockImplementation(() => {
            const pendingResponse = pendingResponses[nextResponse++]
            if (nextResponse === limit + 1) {
                nextQueryStarted.resolve()
            }
            return pendingResponse.promise
        })
        const logics = pendingResponses.map((_, index) =>
            dataNodeLogic({
                key: `scene-${scene}-${index}`,
                query: { kind: NodeKind.HogQLQuery, query: `SELECT ${index}` },
                loadPriority: index,
            })
        )

        jest.useFakeTimers()
        try {
            logics.forEach((logic) => logic.mount())
            jest.advanceTimersByTime(0)
            expect(mockedQuery).toHaveBeenCalledTimes(limit)

            pendingResponses[0].resolve(response)
            await nextQueryStarted.promise
            expect(mockedQuery).toHaveBeenCalledTimes(limit + 1)
        } finally {
            jest.useRealTimers()
            pendingResponses.forEach(({ resolve }) => resolve(response))
            await Promise.all(logics.map((logic) => expectLogic(logic).toFinishAllListeners()))
            logics.forEach((logic) => logic.unmount())
            sceneLogic.unmount()
        }
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
