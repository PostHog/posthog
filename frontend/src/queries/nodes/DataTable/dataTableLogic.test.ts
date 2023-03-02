import { initKeaTests } from '~/test/init'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { expectLogic, partial } from 'kea-test-utils'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableNode, NodeKind } from '~/queries/schema'
import { query } from '~/queries/query'
jest.mock('~/queries/query')

const testUniqueKey = 'testUniqueKey'

describe('dataTableLogic', () => {
    let logic: ReturnType<typeof dataTableLogic.build>

    beforeEach(async () => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => logic?.unmount())

    it('gets the response from dataNodeLogic', async () => {
        const dataTableQuery: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
            },
        }
        logic = dataTableLogic({
            key: testUniqueKey,
            query: dataTableQuery,
        })
        const randomResponse = {}
        ;(query as any).mockResolvedValueOnce(randomResponse)
        logic.mount()
        const builtDataNodeLogic = dataNodeLogic({ key: testUniqueKey, query: dataTableQuery.source })
        await expectLogic(logic).toMount([builtDataNodeLogic])
        await expectLogic(logic).toMatchValues({
            responseLoading: false,
            response: randomResponse,
        })
        await expectLogic(builtDataNodeLogic).toMatchValues({
            responseLoading: false,
            response: randomResponse,
        })

        expect(query).toHaveBeenCalledWith(dataTableQuery.source, expect.anything(), false)
        expect(query).toHaveBeenCalledTimes(1)
    })

    it('rejects if passed anything other than a DataTableNode', async () => {
        expect(() => {
            dataTableLogic({
                key: testUniqueKey,
                query: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                } as any, // explicitly passing bad data
            })
        }).toThrow('dataTableLogic only accepts queries of type DataTableNode')
    })

    it('extracts sourceKind and orderBy', async () => {
        logic = dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            sourceKind: NodeKind.EventsQuery,
            orderBy: ['timestamp DESC'],
        })

        // change props
        dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                    orderBy: ['event'],
                },
            },
        })

        await expectLogic(logic).toMatchValues({
            sourceKind: NodeKind.EventsQuery,
            orderBy: ['event'],
        })

        // change props
        dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.PersonsNode,
                },
            },
        })

        await expectLogic(logic).toMatchValues({
            sourceKind: NodeKind.PersonsNode,
            orderBy: null,
        })
    })

    it('updates local columns if query changed', async () => {
        logic = dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            columnsInQuery: ['*', 'event', 'timestamp'],
        })

        // change props
        dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp', 'properties.foobar'],
                },
            },
        })

        await expectLogic(logic).toMatchValues({
            columnsInQuery: ['*', 'event', 'timestamp', 'properties.foobar'],
        })
    })

    it('adds category rows for default live events table', async () => {
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
            [
                { ...commonResult, timestamp: '2022-12-23T17:00:41.165000Z' },
                'update user properties',
                '2022-12-23T17:00:41.165000Z',
            ],
            [
                { ...commonResult, timestamp: '2022-12-23T16:00:41.165000Z' },
                'update user properties',
                '2022-12-23T16:00:41.165000Z',
            ],
            [
                { ...commonResult, timestamp: '2022-12-22T17:00:41.165000Z' },
                'update user properties',
                '2022-12-22T17:00:41.165000Z',
            ],
            [
                { ...commonResult, timestamp: '2022-12-22T16:00:41.165000Z' },
                'update user properties',
                '2022-12-22T16:00:41.165000Z',
            ],
        ]
        ;(query as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            types: [
                "Tuple(UUID, String, String, DateTime64(6, 'UTC'), Int64, String, String, DateTime64(6, 'UTC'), UUID, DateTime64(3), String)",
                'String',
                "DateTime64(6, 'UTC')",
            ],
            results: results,
            hasMore: true,
        })
        logic = dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                },
            },
        })
        logic.mount()
        expect(query).toHaveBeenCalledTimes(1)

        await expectLogic(logic)
            .toMatchValues({ responseLoading: true })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results }) })
        await expectLogic(logic).toMatchValues({
            dataTableRows: [
                { result: results[0] },
                { label: 'December 23, 2022' },
                { result: results[1] },
                { result: results[2] },
                { label: 'December 22, 2022' },
                { result: results[3] },
                { result: results[4] },
            ],
        })
    })

    it('respects allowSorting', async () => {
        logic = dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                },
                allowSorting: false,
            },
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            canSort: false,
        })

        // change props
        dataTableLogic({
            key: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                },
                allowSorting: true,
            },
        })

        await expectLogic(logic).toMatchValues({
            canSort: true,
        })
    })
})
