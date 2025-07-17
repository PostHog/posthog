import { expectLogic, partial } from 'kea-test-utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { performQuery } from '~/queries/query'
import { DashboardFilter, HogQLVariable, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

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

    it('can load next data for EventsQuery', async () => {
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
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                before: '2022-12-24T17:00:41.165000Z',
                limit: 100,
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
                    before: '2022-12-24T17:00:41.165000Z',
                    limit: 100,
                }),
                response: partial({ results }),
            })
            .delay(0)

        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: setLatestVersionsOnQuery({
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                before: '2022-12-23T17:00:41.165000Z',
                limit: 100,
            }),
            response: partial({ results: [...results, ...results2] }),
        })
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
        expect(logic.cache.autoLoadInterval).toBeTruthy()
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
            false
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
            false
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
            false
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
            false
        )
    })
})
