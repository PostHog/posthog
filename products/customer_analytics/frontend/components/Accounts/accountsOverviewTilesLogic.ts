import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { v4 as uuidv4 } from 'uuid'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AccountsQueryResponse, DataNode } from '~/queries/schema/schema-general'

import { ACCOUNTS_HOGQL_DATA_NODE_KEY } from '../../constants'
import { AccountColumnGroup, AccountColumnOption, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
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

export interface TileFilter {
    tileId: string
    expression: string
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

export function tileFilterFor(tile: AccountsOverviewTile): TileFilter | null {
    const expression = tileToRowFilter(tile)
    return expression ? { tileId: tile.id, expression } : null
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
            accountsColumnConfigLogic,
            ['accountsColumnGroups'],
            dataNodeLogic({ key: ACCOUNTS_HOGQL_DATA_NODE_KEY, query: {} as DataNode }),
            ['response as accountsResponse', 'responseLoading as accountsResponseLoading'],
        ],
    })),
    actions({
        addTile: (tile: Omit<AccountsOverviewTile, 'id'> & { id?: string }) => ({ tile }),
        updateTile: (id: string, tile: Omit<AccountsOverviewTile, 'id'>) => ({ id, tile }),
        removeTile: (id: string) => ({ id }),
        moveTile: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        toggleTileSelection: (tile: AccountsOverviewTile) => ({ tile }),
        setTileFilter: (filter: TileFilter | null) => ({ filter }),
        resetTiles: true,
        showEditor: true,
        hideEditor: true,
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
        tileFilter: [
            null as TileFilter | null,
            {
                setTileFilter: (_, { filter }) => filter,
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
        metrics: [
            (s) => [s.reconciledTiles],
            (tiles: AccountsOverviewTile[]): string[] => tiles.map(tileMetricExpression),
        ],
        tileValues: [
            (s) => [s.accountsResponse, s.reconciledTiles],
            (response: AccountsQueryResponse | null, tiles: AccountsOverviewTile[]): Record<string, number | null> =>
                parseTileValues(response, tiles),
        ],
        tilesLoading: [(s) => [s.accountsResponseLoading], (loading: boolean): boolean => loading],
        selectedTileId: [(s) => [s.tileFilter], (filter: TileFilter | null): string | null => filter?.tileId ?? null],
    }),
    listeners(({ actions, values }) => ({
        removeTile: ({ id }) => {
            if (values.tileFilter?.tileId === id) {
                actions.setTileFilter(null)
            }
        },
        resetTiles: () => {
            if (values.tileFilter) {
                actions.setTileFilter(null)
            }
        },
        updateTile: ({ id, tile }) => {
            if (values.tileFilter?.tileId !== id) {
                return
            }
            actions.setTileFilter(tileFilterFor({ ...tile, id }))
        },
        toggleTileSelection: ({ tile }) => {
            const next = tileFilterFor(tile)
            if (!next) {
                return
            }
            actions.setTileFilter(values.tileFilter?.tileId === tile.id ? null : next)
        },
    })),
])
