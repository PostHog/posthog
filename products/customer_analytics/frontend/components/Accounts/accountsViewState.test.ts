import { ACCOUNTS_HOGQL_DEFAULT_SELECT } from './accountsColumnConfigLogic'
import {
    deserializeAccountsView,
    normalizeRoleFilter,
    orderByToSortOrder,
    serializeAccountsView,
    sortOrderToOrderBy,
} from './accountsViewState'
import { DEFAULT_TILES } from './constants'

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
        const state = {
            columns: ['name', 'csm'],
            sortOrder: { column: 'csm' as const, direction: 'desc' as const },
            filters: {
                search: 'acme',
                tags: ['enterprise'],
                unassigned: false,
                assignedTo: [1, 2, 3],
                tileFilter: { tileId: 't1', expression: 'mrr > 100' },
            },
            tiles: [{ id: 't1', label: 'Accounts', metric: { type: 'count' as const } }],
        }
        const payload = serializeAccountsView(state)
        expect(payload.order_by).toEqual(['csm DESC'])
        expect(payload.columns).toEqual(['name', 'csm'])
        expect(payload.properties).toEqual({ tiles: state.tiles })
        expect(deserializeAccountsView(payload)).toEqual(state)
    })

    it('omits empty filters and serializes no sort', () => {
        const payload = serializeAccountsView({
            columns: [...ACCOUNTS_HOGQL_DEFAULT_SELECT],
            sortOrder: null,
            filters: {
                search: '',
                tags: [],
                unassigned: false,
                assignedTo: [],
                tileFilter: null,
            },
            tiles: [...DEFAULT_TILES],
        })
        expect(payload.filters).toEqual({})
        expect(payload.order_by).toEqual([])
    })

    it('treats a legacy columns-only row (filters [], no properties) as defaults', () => {
        const state = deserializeAccountsView({ columns: ['name'], order_by: null, filters: [], properties: {} })
        expect(state.filters).toEqual({
            search: '',
            tags: [],
            unassigned: false,
            assignedTo: [],
            tileFilter: null,
        })
        expect(state.tiles).toEqual(DEFAULT_TILES)
        expect(state.sortOrder).toBeNull()
    })

    it('falls back to default columns when a row has none', () => {
        const state = deserializeAccountsView({ columns: [], order_by: [], filters: {}, properties: {} })
        expect(state.columns).toEqual(ACCOUNTS_HOGQL_DEFAULT_SELECT)
    })
})
