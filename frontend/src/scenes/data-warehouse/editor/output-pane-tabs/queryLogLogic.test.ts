import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { queryLogLogic } from './queryLogLogic'

const QUERY_LOG_COLUMNS = [
    'query_id',
    'query',
    'query_start_time',
    'query_duration_ms',
    'status',
    'exception_code',
    'result_rows',
]

function queryLogRow(index: number): any[] {
    return [`query-${index}`, `SELECT ${index}`, '2026-07-01 00:00:00', 12, 'QueryFinish', 0, 1]
}

function queryLogResponseMock(rowCount: number): Parameters<typeof useMocks>[0] {
    return {
        post: {
            '/api/environments/:team_id/query/HogQLQuery/': () => [
                200,
                {
                    results: Array.from({ length: rowCount }, (_, index) => queryLogRow(index)),
                    columns: QUERY_LOG_COLUMNS,
                },
            ],
        },
    }
}

describe('queryLogLogic', () => {
    let logic: ReturnType<typeof queryLogLogic.build>

    beforeEach(async () => {
        useMocks(queryLogResponseMock(1))
        initKeaTests()
        userLogic.mount()
        await expectLogic(userLogic).toFinishAllListeners()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the query log on mount and maps result rows to objects', async () => {
        logic = queryLogLogic({ tabId: 'test-tab' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadQueryLog', 'loadQueryLogSuccess'])

        expect(logic.values.queryLog).toEqual([
            {
                query_id: 'query-0',
                query: 'SELECT 0',
                query_start_time: '2026-07-01 00:00:00',
                query_duration_ms: 12,
                status: 'QueryFinish',
                exception_code: 0,
                result_rows: 1,
            },
        ])
        expect(logic.values.hasMore).toBe(false)
    })

    it('offers load more after a full page and appends the next page', async () => {
        useMocks(queryLogResponseMock(100))
        logic = queryLogLogic({ tabId: 'test-tab' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadQueryLogSuccess'])
        expect(logic.values.queryLog).toHaveLength(100)
        expect(logic.values.hasMore).toBe(true)

        useMocks(queryLogResponseMock(3))
        logic.actions.loadMoreQueryLog()
        await expectLogic(logic).toDispatchActions(['loadMoreQueryLogSuccess'])

        expect(logic.values.queryLog).toHaveLength(103)
        expect(logic.values.hasMore).toBe(false)
    })
})
