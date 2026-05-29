import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { performQuery } from '~/queries/query'
import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { AccountColumnGroup, AccountColumnOption, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic, RoleFilterValue } from './accountsLogic'
import type { accountsOverviewTilesLogicType } from './accountsOverviewTilesLogicType'

export const ACCOUNTS_OVERVIEW_TILE_ID_PREFIX = 'tile_'

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

function quoteHogqlString(value: string): string {
    return `'${value.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`
}

export interface OverviewFilters {
    searchQuery: string
    tagsFilter: string[]
    allRolesUnassigned: boolean
    csmFilter: RoleFilterValue
    accountExecutiveFilter: RoleFilterValue
    accountOwnerFilter: RoleFilterValue
}

// Build a HogQL WHERE clause matching `AccountsQueryRunner.to_query`. Keep the
// logic aligned with the backend so tile counts agree with the rows the user
// sees in the table.
function buildWhereClause(filters: OverviewFilters): string {
    const conditions: string[] = []

    if (filters.searchQuery.trim()) {
        const pattern = quoteHogqlString(`%${filters.searchQuery.trim()}%`)
        conditions.push(`(name ILIKE ${pattern} OR external_id ILIKE ${pattern})`)
    }

    if (filters.tagsFilter.length > 0) {
        const tagList = filters.tagsFilter.map(quoteHogqlString).join(', ')
        conditions.push(
            `id IN (SELECT ti.account_id FROM system._account_tagged_items AS ti ` +
                `INNER JOIN system.tags AS t ON t.id = ti.tag_id ` +
                `WHERE t.name IN (${tagList}))`
        )
    }

    const ROLE_KEYS = [
        { value: filters.csmFilter, jsonKey: 'csm' },
        { value: filters.accountExecutiveFilter, jsonKey: 'account_executive' },
        { value: filters.accountOwnerFilter, jsonKey: 'account_owner' },
    ]

    for (const { value, jsonKey } of ROLE_KEYS) {
        if (value === null || value === undefined) {
            continue
        }
        if (typeof value === 'number' && Number.isFinite(value)) {
            conditions.push(`JSONExtract(properties, ${quoteHogqlString(jsonKey)}, 'id', 'Nullable(Int64)') = ${value}`)
        }
    }

    if (filters.allRolesUnassigned) {
        for (const { jsonKey } of ROLE_KEYS) {
            conditions.push(`isNull(JSONExtract(properties, ${quoteHogqlString(jsonKey)}, 'id', 'Nullable(Int64)'))`)
        }
    }

    return conditions.length ? `WHERE ${conditions.join(' AND ')}` : ''
}

function tileSelectAlias(tile: AccountsOverviewTile): string {
    return `${ACCOUNTS_OVERVIEW_TILE_ID_PREFIX}${tile.id.replace(/[^A-Za-z0-9_]/g, '_')}`
}

function tileSelectExpression(tile: AccountsOverviewTile): string {
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

export function buildOverviewHogqlQuery(tiles: AccountsOverviewTile[], filters: OverviewFilters): HogQLQuery | null {
    if (tiles.length === 0) {
        return null
    }
    const selectClauses = tiles.map((tile) => `${tileSelectExpression(tile)} AS ${tileSelectAlias(tile)}`).join(', ')
    const whereClause = buildWhereClause(filters)
    const query = `SELECT ${selectClauses} FROM system.accounts ${whereClause}`.trim()
    return {
        kind: NodeKind.HogQLQuery,
        query,
        tags: {
            ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
            name: 'customer_analytics_accounts_overview',
        },
    }
}

export function parseTileValues(
    response: { results?: unknown } | null,
    tiles: AccountsOverviewTile[]
): Record<string, number | null> {
    const values: Record<string, number | null> = {}
    const results = response && Array.isArray(response.results) ? response.results : null
    const row = results && Array.isArray(results[0]) ? (results[0] as unknown[]) : null
    if (!row) {
        for (const tile of tiles) {
            values[tile.id] = null
        }
        return values
    }
    tiles.forEach((tile, index) => {
        const raw = row[index]
        if (raw === null || raw === undefined) {
            values[tile.id] = null
            return
        }
        const numeric = typeof raw === 'number' ? raw : Number(raw)
        values[tile.id] = Number.isFinite(numeric) ? numeric : null
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
                'refresh as refreshAccounts',
            ],
        ],
    })),
    actions({
        addTile: (tile: Omit<AccountsOverviewTile, 'id'> & { id?: string }) => ({ tile }),
        updateTile: (id: string, tile: Omit<AccountsOverviewTile, 'id'>) => ({ id, tile }),
        removeTile: (id: string) => ({ id }),
        moveTile: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
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
        overviewHogqlQuery: [
            (s) => [s.reconciledTiles, s.overviewFilters],
            (tiles: AccountsOverviewTile[], filters: OverviewFilters): HogQLQuery | null =>
                buildOverviewHogqlQuery(tiles, filters),
        ],
        tileValues: [
            (s) => [s.tileQueryResponse, s.reconciledTiles],
            (response: { results?: unknown } | null, tiles: AccountsOverviewTile[]): Record<string, number | null> =>
                parseTileValues(response, tiles),
        ],
    }),
    loaders(({ values }) => ({
        tileQueryResponse: [
            null as { results?: unknown } | null,
            {
                loadTileValues: async (_: unknown, breakpoint) => {
                    const query = values.overviewHogqlQuery
                    if (!query) {
                        return null
                    }
                    await breakpoint(300)
                    try {
                        const response = await performQuery(query)
                        breakpoint()
                        return response as { results?: unknown }
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
    listeners(({ actions }) => {
        const reload = (): void => actions.loadTileValues(undefined)
        return {
            addTile: reload,
            updateTile: reload,
            removeTile: reload,
            moveTile: reload,
            resetTiles: reload,
            refreshTileValues: reload,
            setSearchQuery: reload,
            setTagsFilter: reload,
            setAllRolesUnassigned: reload,
            setCsmFilter: reload,
            setAccountExecutiveFilter: reload,
            setAccountOwnerFilter: reload,
            refreshAccounts: reload,
        }
    }),
    afterMount(({ actions }) => {
        actions.loadTileValues(undefined)
    }),
])
