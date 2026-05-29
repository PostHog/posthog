import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { performQuery } from '~/queries/query'
import { AccountsQuery, AccountsQueryResponse, NodeKind } from '~/queries/schema/schema-general'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { AccountColumnGroup, AccountColumnOption, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic, RoleFilterValue, TileFilter } from './accountsLogic'
import type { accountsOverviewTilesLogicType } from './accountsOverviewTilesLogicType'

export const ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS = ['>', '>=', '<', '<=', '=', '!='] as const
export type AccountsOverviewThresholdOperator = (typeof ACCOUNTS_OVERVIEW_THRESHOLD_OPERATORS)[number]

export type AccountsOverviewTileMetric =
    | { type: 'count' }
    | { type: 'sum'; columnExpression: string; columnLabel: string }
    | { type: 'avg'; columnExpression: string; columnLabel: string }
    | {
          type: 'count_threshold'
          columnExpression: string
          columnLabel: string
          operator: AccountsOverviewThresholdOperator
          value: number
      }

export type AccountsOverviewTileMetricType = AccountsOverviewTileMetric['type']

export interface AccountsOverviewTile {
    id: string
    label: string
    metric: AccountsOverviewTileMetric
}

const NUMERIC_FIELD_TYPES = new Set(['integer', 'float', 'decimal'])

const DEFAULT_TILES: AccountsOverviewTile[] = [{ id: 'default-accounts', label: 'Accounts', metric: { type: 'count' } }]

const teamIdForPersistence = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = {
    persist: true,
    prefix: `${teamIdForPersistence}_customer_analytics_accounts_overview__`,
}

// Strip a trailing `AS alias` from a HogQL fragment — column entries in the
// account column groups carry aliases (e.g. `accounts.health.score AS score`)
// so the data table can address them by name, but aggregation expressions
// must reference the bare column.
export function stripHogqlAlias(expression: string): string {
    return expression.replace(/\s+AS\s+[A-Za-z_][\w]*\s*$/i, '').trim()
}

export function isNumericColumnType(type: string | undefined): boolean {
    return !!type && NUMERIC_FIELD_TYPES.has(type)
}

export function numericColumnOptions(groups: AccountColumnGroup[]): AccountColumnOption[] {
    return groups
        .filter((group) => !group.isFreeform)
        .flatMap((group) =>
            group.options
                .filter((option) => isNumericColumnType(option.type))
                .map((option) => ({
                    ...option,
                    expression: stripHogqlAlias(option.expression),
                }))
        )
}

export function tileMetricExpression(tile: AccountsOverviewTile): string {
    const { metric } = tile
    switch (metric.type) {
        case 'count':
            return 'count()'
        case 'sum':
            return `sum(${metric.columnExpression})`
        case 'avg':
            return `avg(${metric.columnExpression})`
        case 'count_threshold':
            return `countIf(${metric.columnExpression} ${metric.operator} ${metric.value})`
    }
}

// A tile only acts as a row-level predicate when it represents an
// inherently row-level condition. `count_threshold` does; `count`/`sum`/`avg`
// describe the whole set, not a subset.
export function tileToRowFilter(tile: AccountsOverviewTile): string | null {
    if (tile.metric.type !== 'count_threshold') {
        return null
    }
    const { columnExpression, operator, value } = tile.metric
    return `${columnExpression} ${operator} ${value}`
}

export function isTileClickable(tile: AccountsOverviewTile): boolean {
    return tileToRowFilter(tile) !== null
}

export interface OverviewFilters {
    searchQuery: string
    tagsFilter: string[]
    allRolesUnassigned: boolean
    csmFilter: RoleFilterValue
    accountExecutiveFilter: RoleFilterValue
    accountOwnerFilter: RoleFilterValue
}

// Build an AccountsQuery in metrics mode — the backend runner reuses the same
// WHERE clause it builds for the table, so tile values stay consistent with
// the rows the user sees.
export function buildOverviewAccountsQuery(
    tiles: AccountsOverviewTile[],
    filters: OverviewFilters
): AccountsQuery | null {
    if (tiles.length === 0) {
        return null
    }
    const query: AccountsQuery = {
        kind: NodeKind.AccountsQuery,
        metrics: tiles.map(tileMetricExpression),
        select: [],
        tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_overview' },
    }
    const trimmed = filters.searchQuery.trim()
    if (trimmed) {
        query.search = trimmed
    }
    if (filters.tagsFilter.length > 0) {
        query.tagNames = filters.tagsFilter
    }
    if (filters.allRolesUnassigned) {
        query.allRolesUnassigned = true
    }
    if (filters.csmFilter !== null) {
        query.csm = filters.csmFilter
    }
    if (filters.accountExecutiveFilter !== null) {
        query.accountExecutive = filters.accountExecutiveFilter
    }
    if (filters.accountOwnerFilter !== null) {
        query.accountOwner = filters.accountOwnerFilter
    }
    return query
}

function readNumeric(raw: unknown): number | null {
    if (raw === null || raw === undefined) {
        return null
    }
    const numeric = typeof raw === 'number' ? raw : Number(raw)
    return Number.isFinite(numeric) ? numeric : null
}

export function parseTileValues(
    response: AccountsQueryResponse | null,
    tiles: AccountsOverviewTile[]
): Record<string, number | null> {
    const values: Record<string, number | null> = {}
    const metricsResults = response?.metricsResults
    tiles.forEach((tile, index) => {
        const raw = Array.isArray(metricsResults) ? metricsResults[index] : null
        values[tile.id] = readNumeric(raw)
    })
    return values
}

// Drop tiles that point at a column no longer exposed by the schema. We can't
// tell from a saved tile alone whether `metric.columnExpression` is still valid
// HogQL, so we conservatively reconcile against the live column groups.
function reconcileTilesAgainstSchema(
    tiles: AccountsOverviewTile[],
    numericExpressions: Set<string>
): AccountsOverviewTile[] {
    return tiles.filter((tile) => {
        if (tile.metric.type === 'count') {
            return true
        }
        return numericExpressions.has(tile.metric.columnExpression)
    })
}

export const accountsOverviewTilesLogic = kea<accountsOverviewTilesLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsOverviewTilesLogic']),
    connect(() => ({
        values: [
            accountsLogic,
            [
                'searchQuery',
                'tagsFilter',
                'allRolesUnassigned',
                'csmFilter',
                'accountExecutiveFilter',
                'accountOwnerFilter',
                'tileFilter',
            ],
            accountsColumnConfigLogic,
            ['accountsColumnGroups'],
        ],
        actions: [
            accountsLogic,
            [
                'setSearchQuery',
                'setTagsFilter',
                'setAllRolesUnassigned',
                'setCsmFilter',
                'setAccountExecutiveFilter',
                'setAccountOwnerFilter',
                'setTileFilter',
                'refresh as refreshAccounts',
            ],
        ],
    })),
    actions({
        addTile: (tile: Omit<AccountsOverviewTile, 'id'> & { id?: string }) => ({ tile }),
        updateTile: (id: string, tile: Omit<AccountsOverviewTile, 'id'>) => ({ id, tile }),
        removeTile: (id: string) => ({ id }),
        moveTile: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        toggleTileSelection: (tile: AccountsOverviewTile) => ({ tile }),
        resetTiles: true,
        showEditor: true,
        hideEditor: true,
        refreshTileValues: true,
    }),
    reducers(() => ({
        tiles: [
            DEFAULT_TILES,
            persistConfig,
            {
                addTile: (
                    state: AccountsOverviewTile[],
                    { tile }: { tile: Omit<AccountsOverviewTile, 'id'> & { id?: string } }
                ) => [...state, { ...tile, id: tile.id || uuidv4() }],
                updateTile: (
                    state: AccountsOverviewTile[],
                    { id, tile }: { id: string; tile: Omit<AccountsOverviewTile, 'id'> }
                ) => state.map((t) => (t.id === id ? { ...tile, id } : t)),
                removeTile: (state: AccountsOverviewTile[], { id }: { id: string }) => state.filter((t) => t.id !== id),
                moveTile: (
                    state: AccountsOverviewTile[],
                    { oldIndex, newIndex }: { oldIndex: number; newIndex: number }
                ) => {
                    if (oldIndex === newIndex || oldIndex < 0 || oldIndex >= state.length) {
                        return state
                    }
                    const next = [...state]
                    const [removed] = next.splice(oldIndex, 1)
                    next.splice(newIndex, 0, removed)
                    return next
                },
                resetTiles: () => [...DEFAULT_TILES],
            },
        ],
        editorVisible: [
            false,
            {
                showEditor: () => true,
                hideEditor: () => false,
            },
        ],
    })),
    loaders(({ values }) => ({
        tileQueryResponse: [
            null as AccountsQueryResponse | null,
            {
                loadTileValues: async (_: unknown, breakpoint) => {
                    const query = values.overviewQuery
                    if (!query) {
                        return null
                    }
                    await breakpoint(300)
                    try {
                        const response = await performQuery(query)
                        breakpoint()
                        return response as AccountsQueryResponse
                    } catch (error) {
                        posthog.captureException(error as Error, {
                            scope: 'accountsOverviewTilesLogic.loadTileValues',
                        })
                        throw error
                    }
                },
            },
        ],
    })),
    selectors({
        numericColumns: [
            (s) => [s.accountsColumnGroups],
            (groups: AccountColumnGroup[]): AccountColumnOption[] => numericColumnOptions(groups),
        ],
        numericColumnExpressions: [
            (s) => [s.numericColumns],
            (options: AccountColumnOption[]): Set<string> => new Set(options.map((o) => o.expression)),
        ],
        reconciledTiles: [
            (s) => [s.tiles, s.numericColumnExpressions],
            (tiles: AccountsOverviewTile[], expressions: Set<string>): AccountsOverviewTile[] =>
                reconcileTilesAgainstSchema(tiles, expressions),
        ],
        overviewFilters: [
            (s) => [
                s.searchQuery,
                s.tagsFilter,
                s.allRolesUnassigned,
                s.csmFilter,
                s.accountExecutiveFilter,
                s.accountOwnerFilter,
            ],
            (
                searchQuery: string,
                tagsFilter: string[],
                allRolesUnassigned: boolean,
                csmFilter: RoleFilterValue,
                accountExecutiveFilter: RoleFilterValue,
                accountOwnerFilter: RoleFilterValue
            ): OverviewFilters => ({
                searchQuery,
                tagsFilter,
                allRolesUnassigned,
                csmFilter,
                accountExecutiveFilter,
                accountOwnerFilter,
            }),
        ],
        overviewQuery: [
            (s) => [s.reconciledTiles, s.overviewFilters],
            (tiles: AccountsOverviewTile[], filters: OverviewFilters): AccountsQuery | null =>
                buildOverviewAccountsQuery(tiles, filters),
        ],
        tileValues: [
            (s) => [s.tileQueryResponse, s.reconciledTiles],
            (response: AccountsQueryResponse | null, tiles: AccountsOverviewTile[]): Record<string, number | null> =>
                parseTileValues(response, tiles),
        ],
        selectedTileId: [(s) => [s.tileFilter], (filter: TileFilter | null): string | null => filter?.tileId ?? null],
    }),
    listeners(({ actions, values }) => {
        const reload = (): void => actions.loadTileValues(undefined)
        return {
            addTile: reload,
            updateTile: reload,
            removeTile: ({ id }) => {
                if (values.tileFilter?.tileId === id) {
                    actions.setTileFilter(null)
                }
                reload()
            },
            moveTile: reload,
            resetTiles: () => {
                if (values.tileFilter) {
                    actions.setTileFilter(null)
                }
                reload()
            },
            refreshTileValues: reload,
            setSearchQuery: reload,
            setTagsFilter: reload,
            setAllRolesUnassigned: reload,
            setCsmFilter: reload,
            setAccountExecutiveFilter: reload,
            setAccountOwnerFilter: reload,
            refreshAccounts: reload,
            toggleTileSelection: ({ tile }) => {
                const expression = tileToRowFilter(tile)
                if (!expression) {
                    return
                }
                if (values.tileFilter?.tileId === tile.id) {
                    actions.setTileFilter(null)
                } else {
                    actions.setTileFilter({ tileId: tile.id, expression })
                }
            },
        }
    }),
    afterMount(({ actions }) => {
        actions.loadTileValues(undefined)
    }),
])
