import { expectLogic } from 'kea-test-utils'

import { NodeKind, AccountsTableAggregation, AccountsTableRelationshipOperator } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { columnConfigurationsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { ACCOUNTS_COLUMN_CONFIG_KEY } from '../Accounts/accountsColumnConfigLogic'
import { type AccountsOverviewTile } from '../Accounts/accountsOverviewTilesLogic'
import { getAccountsViewSession } from '../Accounts/accountsViewSessionLogic'
import { accountsViewIdStorageKey } from '../Accounts/accountsViewState'
import { indexProductUsageBreadth, indexProductUsageCounts, productUsageCellKey } from './productUsageData'
import { productUsageGridLogic } from './productUsageGridLogic'
import { buildProductUsageOverviewQuery, productUsageOverviewLogic } from './productUsageOverviewLogic'

jest.mock('products/product_analytics/frontend/generated/api', () => ({
    ...jest.requireActual('products/product_analytics/frontend/generated/api'),
    columnConfigurationsRetrieve: jest.fn(),
}))
const retrieve = columnConfigurationsRetrieve as jest.Mock
const tiles: AccountsOverviewTile[] = [
    {
        id: 'arr',
        label: 'ARR',
        metric: {
            type: 'sum',
            columnExpression: 'accounts.custom_properties.values.`12345678-1234-1234-1234-123456789abc`',
            columnLabel: 'MRR',
            scale: 12,
        },
        format: 'currency',
    },
]

describe('book overview and row summaries', () => {
    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        retrieve.mockReset()
    })
    it('waits for settled filters before rebuilding the overview query', async () => {
        const grid = productUsageGridLogic()
        grid.mount()
        const overview = productUsageOverviewLogic()
        overview.mount()
        await expectLogic(overview).toFinishAllListeners()
        overview.actions.loadTilesSuccess(tiles)
        const initialQuery = overview.values.query
        grid.actions.setControls({ search: 'A' })
        grid.actions.setControls({ search: 'Acorn' })
        expect(overview.values.query).toBe(initialQuery)
        await expectLogic(grid).toFinishAllListeners()
        expect(overview.values.query?.filters).toContainEqual({ kind: 'search', query: 'Acorn' })
        overview.unmount()
        grid.unmount()
    })
    it('reuses configured metric semantics and scopes aggregates with the book filters', () => {
        expect(
            buildProductUsageOverviewQuery(
                { search: 'Acorn', assignedTo: [5], assignmentStatus: 'all', relationshipId: 'role' },
                tiles
            )
        ).toMatchObject({
            kind: NodeKind.AccountsTableQuery,
            columns: [],
            metrics: [
                {
                    kind: 'aggregate',
                    aggregation: AccountsTableAggregation.Sum,
                    column: { kind: 'custom_property', definitionId: '12345678-1234-1234-1234-123456789abc' },
                    scale: 12,
                },
            ],
            filters: [
                { kind: 'search', query: 'Acorn' },
                {
                    kind: 'relationship',
                    definitionId: 'role',
                    operator: AccountsTableRelationshipOperator.Exact,
                    userIds: [5],
                },
            ],
        })
    })
    it('reads remembered Accounts tiles without mounting its URL-changing view logic', async () => {
        const grid = productUsageGridLogic()
        grid.mount()
        const { currentTeamId, user } = grid.values
        expect(currentTeamId).toBeTruthy()
        expect(user?.uuid).toBeTruthy()
        localStorage.setItem(accountsViewIdStorageKey(currentTeamId!, user!.uuid), JSON.stringify('view-1'))
        retrieve.mockResolvedValue({
            context_key: ACCOUNTS_COLUMN_CONFIG_KEY,
            columns: [],
            filters: {},
            properties: { tiles },
        })
        const logic = productUsageOverviewLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadTilesSuccess'])
        expect(retrieve).toHaveBeenCalledWith(
            String(currentTeamId),
            'view-1',
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
        expect(logic.values.reconciledTiles).toEqual(tiles)
        logic.unmount()
        grid.unmount()
    })
    it('uses unsaved session tiles and makes no saved-view request', async () => {
        const grid = productUsageGridLogic()
        grid.mount()
        const session = getAccountsViewSession(grid.values.currentTeamId, grid.values.user?.uuid ?? null)
        session.state = {
            columns: [],
            sortOrder: null,
            filters: {
                search: '',
                assignmentStatus: 'all',
                assignedTo: [],
                tags: [],
                tileFilter: null,
                customProperties: [],
                filterGroups: [],
            },
            tiles,
            columnDisplay: {},
        }
        const logic = productUsageOverviewLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadTilesSuccess'])
        expect(logic.values.reconciledTiles).toEqual(tiles)
        expect(retrieve).not.toHaveBeenCalled()
        logic.unmount()
        grid.unmount()
    })
    it('reports a failed configuration load and supports retry without inventing values', async () => {
        const grid = productUsageGridLogic()
        grid.mount()
        localStorage.setItem(
            accountsViewIdStorageKey(grid.values.currentTeamId!, grid.values.user!.uuid),
            JSON.stringify('view-1')
        )
        retrieve
            .mockRejectedValueOnce(new Error('Unavailable'))
            .mockResolvedValueOnce({ context_key: ACCOUNTS_COLUMN_CONFIG_KEY, columns: [], properties: { tiles } })
        const logic = productUsageOverviewLogic()
        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadTilesFailure'])
        expect(logic.values.query).toBeNull()
        expect(logic.values.tilesError).toBeTruthy()
        await expectLogic(logic, () => logic.actions.loadTiles()).toDispatchActions(['loadTilesSuccess'])
        expect(logic.values.tilesError).toBeNull()
        logic.unmount()
        grid.unmount()
    })
    it('counts distinct products across periods without adding duplicate people across products', () => {
        const matrix = {
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            data: [
                { row: 'a', column: 'w1', series: 'pa', users: 12 },
                { row: 'a', column: 'w2', series: 'pa', users: 12 },
                { row: 'a', column: 'w1', series: 'flags', users: 5 },
            ],
            series: [
                { key: 'pa', label: 'PA' },
                { key: 'flags', label: 'Flags' },
            ],
            combinations: [
                { row: 'a', column: 'w1', mask: 1, users: 7 },
                { row: 'a', column: 'w1', mask: 3, users: 5 },
            ],
        }
        expect(indexProductUsageBreadth(matrix, []).get('a')).toBe(2)
        expect(indexProductUsageBreadth(matrix, ['flags']).get('a')).toBe(1)
        expect(indexProductUsageCounts(matrix, ['pa', 'flags']).get(productUsageCellKey('a', 'w1'))).toBe(12)
    })
})
