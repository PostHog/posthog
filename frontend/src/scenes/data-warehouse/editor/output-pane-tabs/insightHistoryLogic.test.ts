import { expectLogic } from 'kea-test-utils'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { getChangeSql, getQueryChange, insightHistoryLogic } from './insightHistoryLogic'

const queryChangeItem = {
    id: 'activity-1',
    user: { first_name: 'Jane', last_name: 'Doe', email: 'jane@example.com' },
    activity: 'updated',
    scope: ActivityScope.INSIGHT,
    item_id: '42',
    detail: {
        name: 'revenue',
        changes: [
            {
                type: 'Insight',
                field: 'query',
                action: 'changed',
                before: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT 1' } },
                after: { kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT 2' } },
            },
        ],
    },
    created_at: '2026-07-01T10:00:00Z',
} as unknown as ActivityLogItem

const nameChangeItem = {
    ...queryChangeItem,
    detail: {
        name: 'revenue',
        changes: [{ type: 'Insight', field: 'name', action: 'changed', before: 'old', after: 'revenue' }],
    },
} as unknown as ActivityLogItem

// Chart settings edits touch the query JSON but leave the SQL text untouched
const settingsOnlyChangeItem = {
    ...queryChangeItem,
    detail: {
        name: 'revenue',
        changes: [
            {
                type: 'Insight',
                field: 'query',
                action: 'changed',
                before: {
                    kind: 'DataVisualizationNode',
                    source: { kind: 'HogQLQuery', query: 'SELECT 2' },
                    display: 'ActionsTable',
                },
                after: {
                    kind: 'DataVisualizationNode',
                    source: { kind: 'HogQLQuery', query: 'SELECT 2' },
                    display: 'BoldNumber',
                },
            },
        ],
    },
} as unknown as ActivityLogItem

describe('insightHistoryLogic', () => {
    describe('getChangeSql', () => {
        it.each([
            [{ kind: 'DataVisualizationNode', source: { kind: 'HogQLQuery', query: 'SELECT 1' } }, 'SELECT 1'],
            [{ source: { query: '   ' } }, null],
            [{ source: {} }, null],
            [{}, null],
            [null, null],
            ['SELECT 1', null],
        ])('extracts SQL from %p as %p', (changeSide, expected) => {
            expect(getChangeSql(changeSide as any)).toEqual(expected)
        })
    })

    describe('getQueryChange', () => {
        it('finds the query change on an item and ignores non-query changes', () => {
            expect(getQueryChange(queryChangeItem)?.field).toEqual('query')
            expect(getQueryChange(nameChangeItem)).toBeNull()
        })

        it('ignores query changes where the SQL text is unchanged (settings-only edits)', () => {
            expect(getQueryChange(settingsOnlyChangeItem)).toBeNull()
        })
    })

    describe('loading', () => {
        let logic: ReturnType<typeof insightHistoryLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team_id/activity_log/': () => [
                        200,
                        { results: [settingsOnlyChangeItem, queryChangeItem, nameChangeItem], count: 3 },
                    ],
                },
            })
            initKeaTests()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('loads activity on mount and only surfaces query-change versions', async () => {
            logic = insightHistoryLogic({ insightId: 42 })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadActivity', 'loadActivitySuccess'])

            expect(logic.values.activity).toHaveLength(3)
            expect(logic.values.historyComplete).toBe(true)
            expect(logic.values.versions).toEqual([
                {
                    id: 'activity-1',
                    createdAt: '2026-07-01T10:00:00Z',
                    authorName: 'Jane Doe',
                    email: 'jane@example.com',
                    isSystem: false,
                    beforeSql: 'SELECT 1',
                    afterSql: 'SELECT 2',
                },
            ])
        })

        it('pages through the full activity log and concatenates results', async () => {
            const fullPage = Array.from({ length: 100 }, () => queryChangeItem)
            useMocks({
                get: {
                    '/api/projects/:team_id/activity_log/': (req) => {
                        const page = Number(req.url.searchParams.get('page') || '1')
                        return [
                            200,
                            page === 1 ? { results: fullPage, count: 101 } : { results: [nameChangeItem], count: 101 },
                        ]
                    },
                },
            })

            logic = insightHistoryLogic({ insightId: 42 })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadActivity', 'loadActivitySuccess'])

            expect(logic.values.activity).toHaveLength(101)
            expect(logic.values.historyComplete).toBe(true)
        })

        it('marks history incomplete when the page cap is hit', async () => {
            const fullPage = Array.from({ length: 100 }, () => queryChangeItem)
            useMocks({
                get: {
                    '/api/projects/:team_id/activity_log/': () => [200, { results: fullPage, count: 5000 }],
                },
            })

            logic = insightHistoryLogic({ insightId: 42 })
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadActivity', 'loadActivitySuccess'])

            expect(logic.values.activity).toHaveLength(1000)
            expect(logic.values.historyComplete).toBe(false)
        })
    })
})
