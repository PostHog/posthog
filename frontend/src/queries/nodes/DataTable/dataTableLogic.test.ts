import { expectLogic, partial } from 'kea-test-utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { performQuery } from '~/queries/query'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

jest.mock('~/queries/query')

const testUniqueKey = 'testUniqueKey'

function getDataTableQuery(extras?: {
    orderBy?: string[]
    select?: string[]
    allowSorting?: boolean
    showOpenEditorButton?: boolean
}): DataTableNode {
    return setLatestVersionsOnQuery({
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.EventsQuery,
            select: extras?.select || ['*', 'event', 'timestamp'],
            ...(extras?.orderBy ? { orderBy: extras.orderBy } : {}),
        },
        ...(extras?.allowSorting !== undefined ? { allowSorting: extras.allowSorting } : {}),
        ...(extras?.showOpenEditorButton !== undefined ? { showOpenEditorButton: extras.showOpenEditorButton } : {}),
    })
}

describe('dataTableLogic', () => {
    let logic: ReturnType<typeof dataTableLogic.build>

    beforeEach(async () => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    afterEach(() => logic?.unmount())

    it('gets the response from dataNodeLogic', async () => {
        const dataTableQuery: DataTableNode = getDataTableQuery()
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: dataTableQuery,
        })
        const randomResponse = null
        ;(performQuery as any).mockResolvedValueOnce(randomResponse)
        logic.mount()
        const builtDataNodeLogic = dataNodeLogic({ key: testUniqueKey, query: dataTableQuery.source })
        await expectLogic(logic).toMount([builtDataNodeLogic])
        await expectLogic(logic).delay(0).toMatchValues({
            responseLoading: false,
            response: randomResponse,
        })
        await expectLogic(builtDataNodeLogic).toMatchValues({
            responseLoading: false,
            response: randomResponse,
        })

        expect(performQuery).toHaveBeenCalledWith(
            setLatestVersionsOnQuery({ kind: 'EventsQuery', select: ['*', 'event', 'timestamp'] }),
            { signal: expect.any(Object) },
            'blocking',
            expect.any(String),
            expect.any(Function),
            undefined,
            undefined,
            false
        )
        expect(performQuery).toHaveBeenCalledTimes(1)
    })

    it('rejects if passed anything other than a DataTableNode', async () => {
        expect(() => {
            dataTableLogic({
                dataKey: testUniqueKey,
                vizKey: testUniqueKey,
                query: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                } as any, // explicitly passing bad data
            })
        }).toThrow('dataTableLogic only accepts queries of type DataTableNode')
    })

    it('extracts sourceKind and orderBy', async () => {
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery(),
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            sourceKind: NodeKind.EventsQuery,
            orderBy: ['timestamp DESC'],
        })

        // change props
        dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery({ orderBy: ['event'] }),
        })

        await expectLogic(logic)
            .delay(0)
            .toMatchValues({
                sourceKind: NodeKind.EventsQuery,
                orderBy: ['event'],
            })

        // change props
        dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
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
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery(),
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            columnsInQuery: ['*', 'event', 'timestamp'],
        })

        // change props
        dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery({ select: ['*', 'event', 'timestamp', 'properties.foobar'] }),
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
        ;(performQuery as any).mockResolvedValueOnce({
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
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp'],
                },
            },
        })
        logic.mount()
        expect(performQuery).toHaveBeenCalledTimes(1)

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
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery({ allowSorting: false }),
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            canSort: false,
        })

        // change props
        dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery({ allowSorting: true }),
        })

        await expectLogic(logic).delay(0).toMatchValues({
            canSort: true,
        })
    })

    it('defaults to showing the open editor button', async () => {
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery(),
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            queryWithDefaults: expect.objectContaining({
                showOpenEditorButton: true,
            }),
        })
    })

    it('query can set whether showing the open editor button', async () => {
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery({ showOpenEditorButton: false }),
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            queryWithDefaults: expect.objectContaining({
                showOpenEditorButton: false,
            }),
        })
    })

    it('context can set whether showing the open editor button', async () => {
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: getDataTableQuery(),
            context: {
                showOpenEditorButton: false,
            },
        })
        logic.mount()
        await expectLogic(logic).toMatchValues({
            queryWithDefaults: expect.objectContaining({
                showOpenEditorButton: false,
            }),
        })
    })
})
