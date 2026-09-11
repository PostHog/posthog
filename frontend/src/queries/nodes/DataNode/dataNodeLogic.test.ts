import { expectLogic, partial } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import {
    QUERY_SCAN_POLL_DEADLINE_MS,
    QUERY_SCAN_POLL_DELAYS_MS,
    dataNodeLogic,
} from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { DashboardFilter, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

const SCAN_ENDPOINT = '/api/environments/:team_id/query/scan/:cache_key/'
const PENDING_SCAN = { status: 'pending', warnings: [], killed: false }
const DONE_SCAN = {
    status: 'done',
    assistant_prompt: 'Help me get what this query is trying to find, as fast as possible.',
    warnings: [
        {
            type: 'query_scan',
            kind: 'no_event_filter',
            message: 'This query read every event in its date range.',
            fix: 'Add an event filter.',
        },
    ],
    range_share: 0.42,
    project_share: 0.1,
    killed: false,
}

function pendingScanResponse(cacheKey = 'cache-key'): Record<string, unknown> {
    return {
        results: [],
        cache_key: cacheKey,
        query_scan: { mode: 'show', rows_read: 10, duration_ms: 2000, status: 'pending' },
    }
}

jest.mock('~/queries/query', () => {
    return {
        __esModules: true,
        ...jest.requireActual('~/queries/query'),
        performQuery: jest.fn(),
    }
})
const mockedQuery = performQuery as jest.MockedFunction<typeof performQuery>

const testUniqueKey = 'testUniqueKey'

const commonResult = {
    uuid: '01853a90-ba94-0000-8776-e8df5617c3ec',
    event: 'update user properties',
    properties: {},
    team_id: 1,
    distinct_id: '123',
}

describe('dataNodeLogic', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    beforeEach(async () => {
        initKeaTests()
    })
    afterEach(() => logic?.unmount())

    it('calls query to fetch data', async () => {
        const results = {}
        mockedQuery.mockResolvedValueOnce({ results })
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            }),
        })
        logic.mount()
        expect(performQuery).toHaveBeenCalledTimes(1)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: null })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results }) })

        // changing the query should trigger a new query, but keep the results while it's loading
        const results2 = {}
        mockedQuery.mockResolvedValueOnce({ results: results2 })
        dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp', 'person'],
            }),
        })
        expect(performQuery).toHaveBeenCalledTimes(2)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: partial({ results }) })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })

        // passing in a new "deep equal" query object should not trigger a new query
        dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp', 'person'],
            }),
        })
        expect(performQuery).toHaveBeenCalledTimes(2)
        await expectLogic(logic).toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })

        // changing the query kind will clear the results and trigger a new query
        const results3 = {}
        mockedQuery.mockResolvedValueOnce({ results: results3 })
        dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.PersonsNode,
            }),
        })
        expect(performQuery).toHaveBeenCalledTimes(3)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: null })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results: results3 }) })
    })

    it('force refreshes account table results when filters change', async () => {
        const assignedQuery = {
            kind: NodeKind.AccountsTableQuery,
            columns: [],
            filters: [{ kind: 'assigned' as const }],
        }
        mockedQuery.mockResolvedValue({ results: [] })
        logic = dataNodeLogic({ key: testUniqueKey, query: assignedQuery })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDataSuccess'])

        const unassignedQuery = {
            kind: NodeKind.AccountsTableQuery,
            columns: [],
            filters: [{ kind: 'unassigned' as const }],
        }
        mockedQuery.mockClear()
        dataNodeLogic({ key: testUniqueKey, query: unassignedQuery })

        expect(performQuery).toHaveBeenCalledWith(
            unassignedQuery,
            expect.anything(),
            'force_blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            undefined,
            false,
            undefined
        )
    })

    it('can load new data if EventsQuery sorted by timestamp', async () => {
        const results = [
            [
                { ...commonResult, timestamp: '2022-12-24T17:00:41.165000Z' },
                'update user properties',
                '2022-12-24T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results,
            hasMore: true,
        })

        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            }),
        })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({
                responseLoading: true,
                canLoadNewData: true,
                newQuery: setLatestVersionsOnQuery({
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                }),
                response: null,
            })
            .delay(0)

        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNewData: true,
            newQuery: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                after: '2022-12-24T17:00:41.165000Z',
            }),
            response: partial({ results }),
        })

        // load new data

        const results2 = [
            [
                { ...commonResult, uuid: 'new', timestamp: '2022-12-25T17:00:41.165000Z' },
                'update user properties',
                '2022-12-25T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results2,
            hasMore: true,
        })

        logic.actions.loadNewData()
        await expectLogic(logic)
            .toMatchValues({
                responseLoading: true,
                canLoadNewData: true,
                newQuery: setLatestVersionsOnQuery({
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                    after: '2022-12-24T17:00:41.165000Z',
                }),
                response: partial({ results }),
            })
            .delay(0)

        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNewData: true,
            newQuery: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                after: '2022-12-25T17:00:41.165000Z',
            }),
            response: partial({ results: [...results2, ...results] }),
        })

        // higlights new rows
        expect(Array.from(logic.values.highlightedRows)).toEqual([results2[0]])
    })

    it('can not load new data if EventsQuery not sorted by timestamp', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                orderBy: ['event'],
            }),
        })
        const results: any[][] = []
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results,
            hasMore: true,
        })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNewData: false, newQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNewData: false,
            newQuery: null,
            response: partial({ results }),
        })
    })

    it.each([{ event: '$mcp_tool_call' }, { events: ['$mcp_tool_call'] }])(
        'keeps the $event event scope in count queries',
        (eventScope) => {
            const properties = [{ key: '$mcp_is_error', type: 'event', value: true, operator: 'exact' as const }]
            logic = dataNodeLogic({
                autoLoad: false,
                key: testUniqueKey,
                query: setLatestVersionsOnQuery({
                    kind: NodeKind.EventsQuery,
                    select: ['*'],
                    ...eventScope,
                    properties,
                }),
            })
            logic.mount()

            expect(logic.values.totalCountQuery).toMatchObject({
                kind: NodeKind.EventsQuery,
                ...eventScope,
                properties: undefined,
                select: ['count(*)'],
            })
            expect(logic.values.filteredCountQuery).toMatchObject({
                kind: NodeKind.EventsQuery,
                ...eventScope,
                properties,
                select: ['count(*)'],
            })
        }
    )

    it('clamps EventsQuery pagination to the maximum accumulated rows', async () => {
        const results = [
            [
                { ...commonResult, timestamp: '2022-12-24T17:00:41.165000Z' },
                'update user properties',
                '2022-12-24T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results,
            hasMore: true,
        })

        logic = dataNodeLogic({
            key: testUniqueKey,
            maxPaginationRows: 3,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            }),
        })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                before: '2022-12-24T17:00:41.165000Z|01853a90-ba94-0000-8776-e8df5617c3ec',
                limit: 2,
            }),
            response: partial({ results }),
        })

        // load next results

        const results2 = [
            [
                { ...commonResult, uuid: 'new', timestamp: '2022-12-23T17:00:41.165000Z' },
                'update user properties',
                '2022-12-23T17:00:41.165000Z',
            ],
            [
                { ...commonResult, uuid: 'newer', timestamp: '2022-12-22T17:00:41.165000Z' },
                'update user properties',
                '2022-12-22T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results2,
            hasMore: true,
        })

        logic.actions.loadNextData()
        await expectLogic(logic)
            .toMatchValues({
                responseLoading: true,
                canLoadNextData: true,
                nextQuery: setLatestVersionsOnQuery({
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                    before: '2022-12-24T17:00:41.165000Z|01853a90-ba94-0000-8776-e8df5617c3ec',
                    limit: 2,
                }),
                response: partial({ results }),
            })
            .delay(0)

        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: false,
            nextQuery: null,
            response: partial({ results: [...results, ...results2] }),
        })

        await expectLogic(logic, () => logic.actions.loadNextData()).toFinishAllListeners()
        expect(mockedQuery).toHaveBeenCalledTimes(2)
    })

    it('can load next data for PersonsNode', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({ kind: NodeKind.PersonsNode }),
        })
        const results = [{}, {}, {}]
        mockedQuery.mockResolvedValueOnce({ results, next: 'next url' })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.PersonsNode,
                limit: 100,
                offset: 3,
            }),
            response: partial({ results }),
        })
    })

    it('can load next data for TracesQuery', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({ kind: NodeKind.TracesQuery }),
        })
        const results = [{}, {}, {}]
        mockedQuery.mockResolvedValueOnce({ results, hasMore: true })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.TracesQuery,
                limit: 100,
                offset: 3,
            }),
            response: partial({ results }),
        })
    })

    it('can load next data for SessionQuery', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({ kind: NodeKind.SessionQuery, sessionId: 'session-1' }),
        })
        const results = [{}, {}, {}]
        mockedQuery.mockResolvedValueOnce({ results, hasMore: true })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.SessionQuery,
                sessionId: 'session-1',
                limit: 100,
                offset: 3,
            }),
            response: partial({ results }),
        })
    })

    it('can load next data for AccountsQuery', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({ kind: NodeKind.AccountsQuery }),
        })
        const results = [[{}], [{}], [{}]]
        mockedQuery.mockResolvedValueOnce({ results, hasMore: true })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.AccountsQuery,
                limit: 100,
                offset: 3,
            }),
            response: partial({ results }),
        })
    })

    it('can load next data for AccountsTableQuery', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({ kind: NodeKind.AccountsTableQuery, columns: [], filters: [] }),
        })
        const results = [{ id: 'account-1' }, { id: 'account-2' }, { id: 'account-3' }]
        mockedQuery.mockResolvedValueOnce({ results, hasMore: true })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.AccountsTableQuery,
                columns: [],
                filters: [],
                limit: 100,
                offset: 3,
            }),
            response: partial({ results }),
        })
    })

    it('can autoload new data for EventsQuery', async () => {
        const results = [
            [
                { ...commonResult, timestamp: '2022-12-24T17:00:41.165000Z' },
                'update user properties',
                '2022-12-24T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results,
            hasMore: true,
        })

        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            }),
        })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({
                responseLoading: true,
                canLoadNewData: true,
                newQuery: setLatestVersionsOnQuery({
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                }),
                response: null,
                autoLoadToggled: false,
                autoLoadStarted: false,
                autoLoadRunning: false,
            })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNewData: true,
            newQuery: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                after: '2022-12-24T17:00:41.165000Z',
            }),
            response: partial({ results }),
            autoLoadToggled: false,
            autoLoadStarted: false,
            autoLoadRunning: false,
        })

        // load new data

        const results2 = [
            [
                { ...commonResult, uuid: 'new', timestamp: '2022-12-25T17:00:41.165000Z' },
                'update user properties',
                '2022-12-25T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results2,
            hasMore: true,
        })

        // Start the autoloader - this is done in a `useEffect` in the frontend,
        // to track whether the autoload needs to run or not. This is separate
        // from the toggle itself.
        logic.actions.startAutoLoad()

        await expectLogic(logic).toMatchValues({
            newDataLoading: false,
            canLoadNewData: true,
            autoLoadToggled: false,
            autoLoadStarted: true,
            autoLoadRunning: false,
            response: partial({ results }),
        })

        jest.useFakeTimers()

        // Turn on the autoload toggle
        logic.actions.toggleAutoLoad()

        await expectLogic(logic).toDispatchActions(['loadNewData', 'loadNewDataSuccess'])

        await expectLogic(logic).toMatchValues({
            newDataLoading: false,
            canLoadNewData: true,
            autoLoadToggled: true,
            autoLoadStarted: true,
            autoLoadRunning: true,
            response: partial({ results: [...results2, ...results] }),
        })
        expect(Array.from(logic.values.highlightedRows)).toEqual([results2[0]])

        const results3 = [
            [
                { ...commonResult, uuid: 'new3', timestamp: '2022-12-25T17:00:41.165000Z' },
                'update user properties',
                '2022-12-25T17:00:41.165000Z',
            ],
        ]
        mockedQuery.mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results3,
            hasMore: true,
        })

        // Autoload is running in the background and will fire in 5 seconds. Check that there's a background script for this.
        expect(logic.cache.disposables.registry.has('autoLoadInterval')).toBe(true)
        jest.advanceTimersByTime(31000)
        await expectLogic(logic)
            .toDispatchActions(['loadNewData', 'loadNewDataSuccess'])
            .toMatchValues({
                newDataLoading: false,
                canLoadNewData: true,
                autoLoadToggled: true,
                autoLoadStarted: true,
                autoLoadRunning: true,
                response: partial({ results: [...results3, ...results2, ...results] }),
            })
    })

    it('does not call query to fetch data if there are cached results', async () => {
        logic = dataNodeLogic({
            key: 'hasCachedResults',
            query: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            }),
            cachedResults: { result: [1, 2, 3] },
        })
        logic.mount()

        // Query to fetch the count will still be called
        expect(performQuery).toHaveBeenCalledTimes(0)

        await expectLogic(logic).toMatchValues({ response: { result: [1, 2, 3] } })
    })

    it('passes filtersOverride to api', async () => {
        const filtersOverride: DashboardFilter = {
            date_from: '2022-12-24T17:00:41.165000Z',
        }
        const query = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'timestamp'],
        })

        logic = dataNodeLogic({
            key: 'key',
            query,
            filtersOverride,
        })
        logic.mount()

        expect(performQuery).toHaveBeenCalledWith(
            query,
            expect.anything(),
            'blocking',
            expect.any(String),
            expect.any(Function),
            { date_from: '2022-12-24T17:00:41.165000Z' },
            undefined,
            false,
            undefined
        )
    })

    it('passes variablesOverride to api', async () => {
        const variablesOverride: Record<string, HogQLVariable> = {
            test_1: {
                variableId: 'some_id',
                code_name: 'some_name',
                value: 'hello world',
            },
        }

        const query = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'timestamp'],
        })

        logic = dataNodeLogic({
            key: 'key',
            query,
            variablesOverride,
        })
        logic.mount()

        expect(performQuery).toHaveBeenCalledWith(
            query,
            expect.anything(),
            'blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            { test_1: { code_name: 'some_name', value: 'hello world', variableId: 'some_id' } },
            false,
            undefined
        )
    })

    it("doesn't pass undefined filtersOverride to api", async () => {
        const query = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'timestamp'],
        })

        logic = dataNodeLogic({
            key: 'key',
            query,
            filtersOverride: undefined,
        })
        logic.mount()

        expect(performQuery).toHaveBeenCalledWith(
            query,
            expect.anything(),
            'blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            undefined,
            false,
            undefined
        )
    })

    it("doesn't pass undefined variablesOverride to api", async () => {
        const query = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'timestamp'],
        })

        logic = dataNodeLogic({
            key: 'key',
            query,
            variablesOverride: undefined,
        })
        logic.mount()

        expect(performQuery).toHaveBeenCalledWith(
            query,
            expect.anything(),
            'blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            undefined,
            false,
            undefined
        )
    })

    it('passes limitContext to api', async () => {
        const query = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'timestamp'],
        })

        logic = dataNodeLogic({
            key: 'key',
            query,
            limitContext: 'posthog_ai',
        })
        logic.mount()

        expect(performQuery).toHaveBeenCalledWith(
            query,
            expect.anything(),
            'blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            undefined,
            false,
            'posthog_ai'
        )
    })

    it('drops a non-RefreshType refresh argument', async () => {
        // A caller that wires loadData straight to onClick passes a React MouseEvent as refresh;
        // it must never reach performQuery, or the query request body fails to serialize.
        const query = setLatestVersionsOnQuery({
            kind: NodeKind.EventsQuery,
            select: ['*', 'event', 'timestamp'],
        })
        mockedQuery.mockResolvedValue({ results: [] })

        logic = dataNodeLogic({ key: testUniqueKey, query })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadDataSuccess'])
        mockedQuery.mockClear()

        logic.actions.loadData({ type: 'click', target: {} } as any)
        await expectLogic(logic).toDispatchActions(['loadDataSuccess'])

        expect(performQuery).toHaveBeenCalledWith(
            query,
            expect.anything(),
            'blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            undefined,
            false,
            undefined
        )
    })

    const mountWithPendingScan = (): void => {
        mockedQuery.mockResolvedValueOnce(pendingScanResponse())
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: setLatestVersionsOnQuery({ kind: NodeKind.EventsQuery, select: ['*'] }),
        })
        logic.mount()
    }

    it('polls a slow run on a backoff and folds the finished scan into the response', async () => {
        jest.useFakeTimers()
        try {
            let scanCalls = 0
            useMocks({
                get: {
                    [SCAN_ENDPOINT]: () => {
                        scanCalls += 1
                        return [200, scanCalls === 1 ? PENDING_SCAN : DONE_SCAN]
                    },
                },
            })
            mountWithPendingScan()
            await jest.advanceTimersByTimeAsync(0)
            expect(logic.values.queryScan?.summary.status).toBe('pending')

            await jest.advanceTimersByTimeAsync(2000)
            expect(scanCalls).toBe(1)
            expect(logic.values.queryScan?.summary.status).toBe('pending')

            await jest.advanceTimersByTimeAsync(4000)
            expect(scanCalls).toBe(2)
            expect(logic.values.queryScan?.summary.status).toBe('done')
            expect(logic.values.queryScan?.summary.range_share).toBe(0.42)
            expect(logic.values.queryScan?.findings).toHaveLength(1)
            expect(logic.values.queryScan?.assistantPrompt).toBe(DONE_SCAN.assistant_prompt)

            // The analysis is done, so no more asks go out.
            await jest.advanceTimersByTimeAsync(60000)
            expect(scanCalls).toBe(2)

            // A poll outlives the run that started it, so a result for another run must not
            // decorate this response with a share and advice measured somewhere else.
            logic.actions.setQueryScanResult(
                { status: 'done', warnings: [], range_share: 0.9, project_share: 0.9, killed: false },
                'another-cache-key'
            )
            expect(logic.values.queryScan?.summary.status).toBe('pending')
            expect(logic.values.queryScan?.findings).toHaveLength(0)
        } finally {
            jest.useRealTimers()
        }
    })

    it('stops polling when the scan endpoint 404s', async () => {
        jest.useFakeTimers()
        try {
            let scanCalls = 0
            useMocks({
                get: {
                    [SCAN_ENDPOINT]: () => {
                        scanCalls += 1
                        return [404, {}]
                    },
                },
            })
            mountWithPendingScan()
            await jest.advanceTimersByTimeAsync(2000)
            expect(scanCalls).toBe(1)

            // A 404 is what a dead job looks like once its pending slot expires, so the poll ends.
            await jest.advanceTimersByTimeAsync(120000)
            expect(scanCalls).toBe(1)
            expect(logic.values.queryScan?.summary.status).toBe('pending')
        } finally {
            jest.useRealTimers()
        }
    })

    it('stops polling once the run is too old to wait for', async () => {
        jest.useFakeTimers()
        try {
            let scanCalls = 0
            useMocks({
                get: {
                    [SCAN_ENDPOINT]: () => {
                        scanCalls += 1
                        return [200, PENDING_SCAN]
                    },
                },
            })
            mountWithPendingScan()

            await jest.advanceTimersByTimeAsync(QUERY_SCAN_POLL_DEADLINE_MS + 60000)
            const callsByDeadline = scanCalls
            // It kept asking on the repeating 30 s interval, past the fixed backoff steps.
            expect(callsByDeadline).toBeGreaterThan(QUERY_SCAN_POLL_DELAYS_MS.length)

            await jest.advanceTimersByTimeAsync(120000)
            expect(scanCalls).toBe(callsByDeadline)
        } finally {
            jest.useRealTimers()
        }
    })
})
