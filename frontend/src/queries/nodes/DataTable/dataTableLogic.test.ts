import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic, partial } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

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
            false,
            undefined
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

    it.each([
        {
            timezone: 'US/Pacific',
            // 2022-12-24T05:00Z = Dec 23 21:00 PST; 2022-12-24T10:00Z = Dec 24 02:00 PST
            timestamps: ['2022-12-24T10:00:00.000000Z', '2022-12-24T05:00:00.000000Z'],
            expectedLabel: 'December 23, 2022',
        },
        {
            timezone: 'Asia/Tokyo',
            // 2022-12-24T15:00Z = Dec 25 00:00 JST; 2022-12-24T14:00Z = Dec 24 23:00 JST
            timestamps: ['2022-12-24T15:00:00.000000Z', '2022-12-24T14:00:00.000000Z'],
            expectedLabel: 'December 24, 2022',
        },
    ])('groups date headers by project timezone ($timezone)', async ({ timezone, timestamps, expectedLabel }) => {
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({ id: MOCK_TEAM_ID, timezone } as any)

        const commonResult = {
            uuid: '01853a90-ba94-0000-8776-e8df5617c3ec',
            event: 'test event',
            properties: {},
            team_id: 1,
            distinct_id: '123',
        }
        const results = timestamps.map((ts) => [{ ...commonResult, timestamp: ts }, 'test event', ts])
        ;(performQuery as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'],
            types: [
                "Tuple(UUID, String, String, DateTime64(6, 'UTC'), Int64, String, String, DateTime64(6, 'UTC'), UUID, DateTime64(3), String)",
                'String',
                "DateTime64(6, 'UTC')",
            ],
            results,
            hasMore: false,
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

        await expectLogic(logic)
            .toMatchValues({ responseLoading: true })
            .delay(0)
            .toMatchValues({ responseLoading: false })

        await expectLogic(logic).toMatchValues({
            dataTableRows: [{ result: results[0] }, { label: expectedLabel }, { result: results[1] }],
        })
    })

    it('keeps the dataTableRows reference stable when a reload returns deep-equal results', async () => {
        // A poll or reload reparses JSON, so a byte-identical response still arrives as all-new
        // object identities. Without result equality on dataTableRows every row's memoized
        // TableRow re-renders per cycle — the detached-DOM churn this selector exists to prevent.
        const makeResults = (eventName: string = 'pageview'): any[][] => [
            [
                {
                    uuid: '01853a90-ba94-0000-8776-e8df5617c3ec',
                    event: eventName,
                    properties: {},
                    team_id: 1,
                    distinct_id: '123',
                    timestamp: '2022-12-24T17:00:41.165000Z',
                },
                eventName,
                '2022-12-24T17:00:41.165000Z',
            ],
            [
                {
                    uuid: '01853a90-ba94-0000-8776-e8df5617c3ed',
                    event: eventName,
                    properties: {},
                    team_id: 1,
                    distinct_id: '123',
                    timestamp: '2022-12-24T16:00:41.165000Z',
                },
                eventName,
                '2022-12-24T16:00:41.165000Z',
            ],
        ]
        const responseFor = (results: any[][]): Record<string, any> => ({
            columns: ['*', 'event', 'timestamp'],
            types: [
                "Tuple(UUID, String, String, DateTime64(6, 'UTC'), Int64, String, String, DateTime64(6, 'UTC'), UUID, DateTime64(3), String)",
                'String',
                "DateTime64(6, 'UTC')",
            ],
            results,
            hasMore: false,
        })

        ;(performQuery as any).mockResolvedValueOnce(responseFor(makeResults()))
        const dataTableQuery = getDataTableQuery()
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: dataTableQuery,
        })
        logic.mount()
        await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })
        const initialRows = logic.values.dataTableRows
        expect(initialRows).toHaveLength(2)

        const builtDataNodeLogic = dataNodeLogic({ key: testUniqueKey, query: dataTableQuery.source })
        ;(performQuery as any).mockResolvedValueOnce(responseFor(makeResults()))
        builtDataNodeLogic.actions.loadData('force_blocking')
        await expectLogic(builtDataNodeLogic).delay(0).toMatchValues({ responseLoading: false })

        expect(logic.values.dataTableRows).toBe(initialRows)

        // The counter-case: a genuinely changed response must produce fresh rows, or tables go stale.
        ;(performQuery as any).mockResolvedValueOnce(responseFor(makeResults('autocapture')))
        builtDataNodeLogic.actions.loadData('force_blocking')
        await expectLogic(builtDataNodeLogic).delay(0).toMatchValues({ responseLoading: false })

        expect(logic.values.dataTableRows).not.toBe(initialRows)
        expect((logic.values.dataTableRows?.[0]?.result as any[])[1]).toEqual('autocapture')
    })

    it('shows results even when columns in query do not match columns in response', async () => {
        const commonResult = {
            uuid: '01853a90-ba94-0000-8776-e8df5617c3ec',
            event: 'pageview',
            properties: {},
            team_id: 1,
            distinct_id: '123',
        }
        const results = [
            [{ ...commonResult, timestamp: '2022-12-24T17:00:41.165000Z' }, 'pageview', '2022-12-24T17:00:41.165000Z'],
            [{ ...commonResult, timestamp: '2022-12-23T17:00:41.165000Z' }, 'pageview', '2022-12-23T17:00:41.165000Z'],
        ]
        // Simulate the race condition: query has new column but API response still has old columns
        // This happens when applying a table view or adding a column - the query updates immediately
        // but the API response is asynchronous
        ;(performQuery as any).mockResolvedValueOnce({
            columns: ['*', 'event', 'timestamp'], // Response has old columns (without properties.foo)
            types: [
                "Tuple(UUID, String, String, DateTime64(6, 'UTC'), Int64, String, String, DateTime64(6, 'UTC'), UUID, DateTime64(3), String)",
                'String',
                "DateTime64(6, 'UTC')",
            ],
            results: results,
            hasMore: false,
        })
        logic = dataTableLogic({
            dataKey: testUniqueKey,
            vizKey: testUniqueKey,
            query: {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'timestamp', 'properties.foo'], // Query has new column
                },
            },
        })
        logic.mount()
        expect(performQuery).toHaveBeenCalledTimes(1)

        await expectLogic(logic)
            .toMatchValues({ responseLoading: true })
            .delay(0)
            .toMatchValues({ responseLoading: false, response: partial({ results }) })

        // The key assertion: dataTableRows should contain results, not be empty
        // Even though columnsInQuery !== columnsInResponse, we should still show the results
        // Note: Date labels are inserted between results from different days (this is expected behavior)
        await expectLogic(logic).toMatchValues({
            dataTableRows: [{ result: results[0] }, { label: 'December 23, 2022' }, { result: results[1] }],
        })
    })

    describe('stable expansion identity', () => {
        const event = (uuid: string, timestamp: string): any[] => [
            { uuid, event: 'pageview', properties: {}, team_id: 1, distinct_id: 'x', timestamp },
            'pageview',
            timestamp,
        ]
        const responseFor = (results: any[][]): Record<string, any> => ({
            columns: ['*', 'event', 'timestamp'],
            types: [
                "Tuple(UUID, String, String, DateTime64(6, 'UTC'), Int64, String, String, DateTime64(6, 'UTC'), UUID, DateTime64(3), String)",
                'String',
                "DateTime64(6, 'UTC')",
            ],
            results,
            hasMore: false,
        })

        const mountWith = (results: any[][]): DataTableNode => {
            ;(performQuery as any).mockResolvedValueOnce(responseFor(results))
            const dataTableQuery = getDataTableQuery()
            logic = dataTableLogic({
                dataKey: testUniqueKey,
                vizKey: testUniqueKey,
                query: dataTableQuery,
            })
            logic.mount()
            return dataTableQuery
        }

        const reload = (dataTableQuery: DataTableNode, results: any[][]): void => {
            const builtDataNodeLogic = dataNodeLogic({ key: testUniqueKey, query: dataTableQuery.source })
            ;(performQuery as any).mockResolvedValueOnce(responseFor(results))
            builtDataNodeLogic.actions.loadData('force_blocking')
        }

        it('keys expansion on event uuid, so an inserted row does not inherit expansion', async () => {
            // Regression: positional keys meant a refresh that inserted a row before the expanded
            // one transferred expansion to the wrong event. UUID keys keep it on the same event.
            const uuidA = '01853a90-ba94-0000-8776-e8df5617c3ec'
            const dataTableQuery = mountWith([event(uuidA, '2022-12-24T17:00:41.165000Z')])
            await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })

            const { getExpandedRowKey } = logic.values
            const keyA = getExpandedRowKey({ result: event(uuidA, '2022-12-24T17:00:41.165000Z') }, 0)
            expect(keyA).toBe(uuidA)
            logic.actions.toggleRowExpanded(keyA)
            expect(logic.values.expandedRowKeys).toEqual([uuidA])

            // A new event arrives before A in the result set.
            const uuidB = '01853a90-ba94-0000-8776-e8df5617c3eb'
            reload(dataTableQuery, [
                event(uuidB, '2022-12-24T18:00:41.165000Z'),
                event(uuidA, '2022-12-24T17:00:41.165000Z'),
            ])
            await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })

            // A stays expanded; B (now at index 0, where A used to be) does not inherit.
            expect(logic.values.expandedRowKeys).toEqual([uuidA])
            const keyB = logic.values.getExpandedRowKey({ result: event(uuidB, '2022-12-24T18:00:41.165000Z') }, 0)
            expect(logic.values.expandedRowKeys).not.toContain(keyB)
        })

        it('drops expansion keys for events that leave the result set on refresh', async () => {
            // Regression: without reconciliation, expanded UUIDs accumulated unbounded as users
            // paginated or changed queries. Stale keys must be removed when the event disappears.
            const uuidA = '01853a90-ba94-0000-8776-e8df5617c3ec'
            const uuidB = '01853a90-ba94-0000-8776-e8df5617c3ed'
            const dataTableQuery = mountWith([
                event(uuidA, '2022-12-24T17:00:41.165000Z'),
                event(uuidB, '2022-12-24T16:00:41.165000Z'),
            ])
            await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })

            logic.actions.toggleRowExpanded(uuidA)
            logic.actions.toggleRowExpanded(uuidB)
            expect(logic.values.expandedRowKeys).toEqual([uuidA, uuidB])

            // Refresh returns only B — A has fallen out of the window.
            reload(dataTableQuery, [event(uuidB, '2022-12-24T16:00:41.165000Z')])
            await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })

            expect(logic.values.expandedRowKeys).toEqual([uuidB])
        })

        it('toggles and supports multiple expanded events by uuid', async () => {
            const uuidA = '01853a90-ba94-0000-8776-e8df5617c3ec'
            const uuidB = '01853a90-ba94-0000-8776-e8df5617c3ed'
            mountWith([event(uuidA, '2022-12-24T17:00:41.165000Z'), event(uuidB, '2022-12-24T16:00:41.165000Z')])
            await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })

            logic.actions.toggleRowExpanded(uuidA)
            logic.actions.toggleRowExpanded(uuidB)
            expect(logic.values.expandedRowKeys).toEqual([uuidA, uuidB])

            // Collapsing one leaves the other intact.
            logic.actions.toggleRowExpanded(uuidA)
            expect(logic.values.expandedRowKeys).toEqual([uuidB])
        })

        it('falls back to positional index for rows without an event uuid', async () => {
            // Non-event tables and events lacking both uuid and id keep working positionally.
            const ts = '2022-12-24T17:00:41.165000Z'
            const dataTableQuery = {
                kind: NodeKind.DataTableNode,
                source: { kind: NodeKind.EventsQuery, select: ['event', 'timestamp'] },
            } as any
            ;(performQuery as any).mockResolvedValueOnce({
                columns: ['event', 'timestamp'],
                types: ['String', "DateTime64(6, 'UTC')"],
                results: [
                    ['pageview', ts],
                    ['pageview', ts],
                ],
                hasMore: false,
            })
            logic = dataTableLogic({ dataKey: testUniqueKey, vizKey: testUniqueKey, query: dataTableQuery })
            logic.mount()
            await expectLogic(logic).delay(0).toMatchValues({ responseLoading: false })

            // No `*` column, so the key is the row index.
            expect(logic.values.getExpandedRowKey({ result: ['pageview', ts] }, 1)).toBe(1)
            logic.actions.toggleRowExpanded(1)
            expect(logic.values.expandedRowKeys).toEqual([1])
        })
    })
})
