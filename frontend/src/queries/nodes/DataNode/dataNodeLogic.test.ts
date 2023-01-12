import { initKeaTests } from '~/test/init'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { expectLogic, partial } from 'kea-test-utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { NodeKind } from '~/queries/schema'
import { query } from '~/queries/query'
jest.mock('~/queries/query')
const testUniqueKey = 'testUniqueKey'

describe('dataNodeLogic', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    beforeEach(async () => {
        initKeaTests()
        featureFlagLogic.mount()
    })
    afterEach(() => logic?.unmount())

    it('calls query to fetch data', async () => {
        const results = {}
        ;(query as any).mockResolvedValueOnce({ results })
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            },
        })
        logic.mount()
        expect(query).toHaveBeenCalledTimes(1)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: null })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results }) })

        // changing the query should trigger a new query, but keep the results while it's loading
        const results2 = {}
        ;(query as any).mockResolvedValueOnce({ results: results2 })
        dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp', 'person'],
            },
        })
        expect(query).toHaveBeenCalledTimes(2)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: partial({ results }) })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })

        // passing in a new "deep equal" query object should not trigger a new query
        dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp', 'person'],
            },
        })
        expect(query).toHaveBeenCalledTimes(2)
        await expectLogic(logic).toMatchValues({ responseLoading: false, response: partial({ results: results2 }) })

        // changing the query kind will clear the results and trigger a new query
        const results3 = {}
        ;(query as any).mockResolvedValueOnce({ results: results3 })
        dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.PersonsNode,
            },
        })
        expect(query).toHaveBeenCalledTimes(3)
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, response: null })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results: results3 }) })
    })

    it('can load new data if EventsQuery sorted by timestamp', async () => {
        const commonResult = {
            uuid: '01853a90-ba94-0000-8776-e8df5617c3ec',
            event: 'update user properties',
            properties: {},
            team_id: 1,
            distinct_id: '123',
        }
        const results = [
            [
                { ...commonResult, timestamp: '2022-12-24T17:00:41.165000Z' },
                'update user properties',
                '2022-12-24T17:00:41.165000Z',
            ],
        ]
        ;(query as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results,
            hasMore: true,
        })

        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            },
        })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNewData: false, newQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNewData: true,
            newQuery: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                after: '2022-12-24T17:00:41.165000Z',
            },
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
        ;(query as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results2,
            hasMore: true,
        })

        logic.actions.loadNewData()
        await expectLogic(logic)
            .toMatchValues({
                responseLoading: true,
                canLoadNewData: true,
                newQuery: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                    after: '2022-12-24T17:00:41.165000Z',
                },
                response: partial({ results }),
            })
            .delay(0)

        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNewData: true,
            newQuery: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                after: '2022-12-25T17:00:41.165000Z',
            },
            response: partial({ results: [...results2, ...results] }),
        })

        // higlights new rows
        expect(Array.from(logic.values.highlightedRows)).toEqual([results2[0]])
    })

    it('can not load new data if EventsQuery not sorted by timestamp', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                orderBy: ['event'],
            },
        })
        const results: any[][] = []
        ;(query as any).mockResolvedValueOnce({
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
        const commonResult = {
            uuid: '01853a90-ba94-0000-8776-e8df5617c3ec',
            event: 'update user properties',
            properties: {},
            team_id: 1,
            distinct_id: '123',
        }
        const results = [
            [
                { ...commonResult, timestamp: '2022-12-24T17:00:41.165000Z' },
                'update user properties',
                '2022-12-24T17:00:41.165000Z',
            ],
        ]
        ;(query as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results,
            hasMore: true,
        })

        logic = dataNodeLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            },
        })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                before: '2022-12-24T17:00:41.165000Z',
            },
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
        ;(query as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            results: results2,
            hasMore: true,
        })

        logic.actions.loadNextData()
        await expectLogic(logic)
            .toMatchValues({
                responseLoading: true,
                canLoadNextData: true,
                nextQuery: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                    before: '2022-12-24T17:00:41.165000Z',
                },
                response: partial({ results }),
            })
            .delay(0)

        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                before: '2022-12-23T17:00:41.165000Z',
            },
            response: partial({ results: [...results, ...results2] }),
        })
    })

    it('can load next data for PersonsNode', async () => {
        logic = dataNodeLogic({
            key: testUniqueKey,
            query: { kind: NodeKind.PersonsNode },
        })
        const results = [{}, {}, {}]
        ;(query as any).mockResolvedValueOnce({ results, next: 'next url' })
        logic.mount()
        await expectLogic(logic)
            .toMatchValues({ responseLoading: true, canLoadNextData: false, nextQuery: null, response: null })
            .delay(0)
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            canLoadNextData: true,
            nextQuery: {
                kind: NodeKind.PersonsNode,
                limit: 100,
                offset: 3,
            },
            response: partial({ results }),
        })
    })

    it('can autoload new data for EventsQuery', async () => {})
})
