import { AccountsTableAccountField, AccountsTableCustomPropertyOperator } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { ACCOUNTS_DEFAULT_COLUMNS } from './accountsColumnConfigLogic'
import {
    AccountsViewState,
    accountsViewIdStorageKey,
    deserializeAccountsView,
    normalizeRoleFilter,
    orderByToSortOrder,
    readAccountsViewId,
    readAccountsViewSelection,
    serializeAccountsView,
    sortOrderToOrderBy,
    writeAccountsViewId,
} from './accountsViewState'
import { DEFAULT_TILES } from './constants'

describe('accountsViewState', () => {
    describe('saved-view references', () => {
        beforeEach(() => localStorage.clear())
        afterEach(() => {
            localStorage.clear()
            jest.restoreAllMocks()
        })

        it('remembers only the saved ID and name, scoped to a project and user', () => {
            writeAccountsViewId(1, 'user-a', 'view-1', 'First view')
            writeAccountsViewId(1, 'user-b', 'view-2', 'Second view')
            writeAccountsViewId(2, 'user-a', 'view-3', 'Other project')
            expect(JSON.parse(localStorage.getItem(accountsViewIdStorageKey(1, 'user-a'))!)).toEqual({
                id: 'view-1',
                name: 'First view',
            })
            expect(readAccountsViewSelection(1, 'user-a')).toEqual({ id: 'view-1', name: 'First view' })
            expect(readAccountsViewSelection(1, 'user-b')).toEqual({ id: 'view-2', name: 'Second view' })
            expect(readAccountsViewSelection(2, 'user-a')).toEqual({ id: 'view-3', name: 'Other project' })
            localStorage.setItem(accountsViewIdStorageKey(1, 'user-a'), JSON.stringify('legacy-id'))
            expect(readAccountsViewSelection(1, 'user-a')).toEqual({ id: 'legacy-id', name: null })
        })

        it.each(['{invalid', '42', '{}', 'null'])('ignores an invalid remembered reference: %s', (raw) => {
            localStorage.setItem(accountsViewIdStorageKey(1, 'user-a'), raw)
            expect(readAccountsViewId(1, 'user-a')).toBeNull()
        })

        it('keeps the legacy reference when scoped storage is unavailable', () => {
            const legacyKey = 'customerAnalytics.accounts.accountsViewsLogic.1.currentViewId'
            localStorage.setItem(legacyKey, JSON.stringify('view-1'))
            jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
                throw new Error('storage denied')
            })
            expect(() => writeAccountsViewId(1, 'user-a', 'view-1')).not.toThrow()
            expect(localStorage.getItem(legacyKey)).toBe(JSON.stringify('view-1'))
            jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
                throw new Error('storage denied')
            })
            expect(readAccountsViewId(1, 'user-a')).toBeNull()
        })
    })

    describe('sortOrderToOrderBy / orderByToSortOrder', () => {
        it('round-trips a plain ascending column', () => {
            expect(sortOrderToOrderBy({ column: 'name', direction: 'asc' })).toEqual(['name ASC'])
            expect(orderByToSortOrder(['name ASC'])).toEqual({ column: 'name', direction: 'asc' })
        })

        it('round-trips a descending role/tuple column by its logical name', () => {
            expect(sortOrderToOrderBy({ column: 'csm', direction: 'desc' })).toEqual(['csm DESC'])
            expect(orderByToSortOrder(['csm DESC'])).toEqual({ column: 'csm', direction: 'desc' })
        })

        it('treats null / empty as no sort', () => {
            expect(sortOrderToOrderBy(null)).toEqual([])
            expect(orderByToSortOrder([])).toBeNull()
            expect(orderByToSortOrder(null)).toBeNull()
        })

        it('defaults to ascending when the direction token is missing', () => {
            expect(orderByToSortOrder(['health_score'])).toEqual({ column: 'health_score', direction: 'asc' })
        })
    })

    describe('normalizeRoleFilter', () => {
        it('coerces a scalar (legacy link) to an array', () => {
            expect(normalizeRoleFilter(7)).toEqual([7])
        })

        it('drops non-number array entries', () => {
            expect(normalizeRoleFilter([1, 'x', 2])).toEqual([1, 2])
        })

        it('falls back to empty for nullish/garbage', () => {
            expect(normalizeRoleFilter(undefined)).toEqual([])
            expect(normalizeRoleFilter('nope')).toEqual([])
        })
    })

    describe('serializeAccountsView / deserializeAccountsView', () => {
        it('round-trips a fully populated view', () => {
            const state: AccountsViewState = {
                columns: ['name', 'csm'],
                sortOrder: { column: 'csm' as const, direction: 'desc' as const },
                filters: {
                    search: 'acme',
                    assignmentStatus: 'assigned',
                    assignedTo: [1, 2, 3],
                    tags: ['enterprise'],
                    tileFilter: {
                        tileId: 't1',
                        filter: {
                            kind: 'custom_property',
                            definitionId: '11111111-2222-3333-4444-555555555555',
                            operator: AccountsTableCustomPropertyOperator.GreaterThan,
                            values: [100],
                        },
                    },
                    filterGroups: [
                        [
                            {
                                type: PropertyFilterType.AccountCustomProperty as const,
                                key: '11111111-2222-3333-4444-555555555555',
                                operator: PropertyOperator.Exact,
                                value: 'Staged',
                                label: 'Tier',
                            },
                        ],
                    ],
                    customProperties: [
                        {
                            type: PropertyFilterType.Account as const,
                            key: AccountsTableAccountField.IgnoredAt,
                            operator: PropertyOperator.IsSet,
                            value: null,
                            label: 'Ignored at',
                        },
                        {
                            type: PropertyFilterType.AccountCustomProperty as const,
                            key: '11111111-2222-3333-4444-555555555555',
                            operator: PropertyOperator.Exact,
                            value: 'Enterprise',
                            label: 'Tier',
                        },
                    ],
                },
                tiles: [{ id: 't1', label: 'Accounts', metric: { type: 'count' as const } }],
                columnDisplay: {
                    '11111111-2222-3333-4444-555555555555': { mode: 'sparkline' as const, window_days: 30 },
                },
            }
            const payload = serializeAccountsView(state)
            expect(payload.order_by).toEqual(['csm DESC'])
            expect(payload.columns).toEqual(['name', 'csm'])
            expect(payload.properties).toEqual({ tiles: state.tiles, column_display: state.columnDisplay })
            expect(deserializeAccountsView(payload)).toEqual(state)
        })

        it('omits empty filters but always stores the assignment status', () => {
            const payload = serializeAccountsView({
                columns: [...ACCOUNTS_DEFAULT_COLUMNS],
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
                tiles: [...DEFAULT_TILES],
                columnDisplay: {},
            })
            // The status is stored even for the `all` default so reopening the view can't be
            // mistaken for a legacy view (no field), which restores as assigned-only.
            expect(payload.filters).toEqual({ assignmentStatus: 'all' })
            expect(payload.order_by).toEqual([])
            expect(payload.properties).toEqual({ tiles: DEFAULT_TILES })
        })

        it('reads a legacy row with no assignment field as assigned-only', () => {
            const state = deserializeAccountsView({ columns: ['name'], order_by: null, filters: [], properties: {} })
            expect(state.filters).toEqual({
                search: '',
                assignmentStatus: 'assigned',
                assignedTo: [],
                tags: [],
                tileFilter: null,
                customProperties: [],
                filterGroups: [],
            })
            expect(state.tiles).toEqual(DEFAULT_TILES)
            expect(state.sortOrder).toBeNull()
            expect(state.columnDisplay).toEqual({})
        })

        it('reads a legacy unassigned-only row as the unassigned status', () => {
            const state = deserializeAccountsView({ columns: ['name'], order_by: null, filters: { unassigned: true } })
            expect(state.filters.assignmentStatus).toEqual('unassigned')
        })

        it('keeps an explicit stored status distinct from a legacy default', () => {
            expect(deserializeAccountsView({ filters: { assignmentStatus: 'all' } }).filters.assignmentStatus).toEqual(
                'all'
            )
            expect(deserializeAccountsView({ filters: {} }).filters.assignmentStatus).toEqual('assigned')
        })

        it('falls back to default columns when a row has none', () => {
            const state = deserializeAccountsView({ columns: [], order_by: [], filters: {}, properties: {} })
            expect(state.columns).toEqual(ACCOUNTS_DEFAULT_COLUMNS)
        })
    })
})
