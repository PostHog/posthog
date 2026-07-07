import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { objectsEqual } from 'lib/utils/objects'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { AccountsQueryResponse, DataNode } from '~/queries/schema/schema-general'

import type { CustomPropertyDisplayTypeEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_METRICS_DATA_NODE_KEY } from '../../constants'
import { isNumericDisplayType } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import { AccountColumnGroup, AccountColumnOption, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import type { accountsOverviewTilesLogicType } from './accountsOverviewTilesLogicType'
import {
    ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX,
    AccountsEvents,
    AccountsOverviewThresholdOperator,
    DEFAULT_TILES,
    MAX_ACCOUNTS_OVERVIEW_TILES,
    NUMERIC_FIELD_TYPES,
} from './constants'

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

// Strip a trailing `AS alias` from a HogQL fragment — column entries in the
// account column groups carry aliases (e.g. `accounts.health.score AS score`)
// so the data table can address them by name, but aggregation expressions
// must reference the bare column.
export function stripHogqlAlias(expression: string): string {
    return expression.replace(/\s+AS\s+[A-Za-z_][\w]*\s*$/i, '').trim()
}

export function isNumericColumnType(type: string | undefined): boolean {
    if (!type) {
        return false
    }
    // Regular columns carry a HogQL field type; custom-property columns carry a display type.
    return NUMERIC_FIELD_TYPES.has(type) || isNumericDisplayType(type as CustomPropertyDisplayTypeEnumApi)
}

export function numericColumnOptions(groups: AccountColumnGroup[]): AccountColumnOption[] {
    return groups
        .filter((group) => !group.isFreeform)
        .flatMap((group) =>
            group.options
                .filter((option) => isNumericColumnType(option.type))
                .map((option) => {
                    const expression = stripHogqlAlias(option.expression)
                    return {
                        ...option,
                        // Custom-property values are stored as coalesced strings; cast so sum/avg aggregate numerically.
                        expression: group.key === 'custom_properties' ? `toFloatOrNull(${expression})` : expression,
                    }
                })
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

export function diffOverviewTiles(
    before: AccountsOverviewTile[],
    after: AccountsOverviewTile[]
): { changed: boolean; added: number; removed: number; updated: number; reordered: boolean } {
    const beforeById = new Map(before.map((tile) => [tile.id, tile]))
    const afterById = new Map(after.map((tile) => [tile.id, tile]))
    const added = after.filter((tile) => !beforeById.has(tile.id)).length
    const removed = before.filter((tile) => !afterById.has(tile.id)).length
    const updated = after.filter((tile) => {
        const previous = beforeById.get(tile.id)
        return !!previous && !objectsEqual(previous, tile)
    }).length
    const reordered = !objectsEqual(
        before.filter((tile) => afterById.has(tile.id)).map((tile) => tile.id),
        after.filter((tile) => beforeById.has(tile.id)).map((tile) => tile.id)
    )
    return { changed: added > 0 || removed > 0 || updated > 0 || reordered, added, removed, updated, reordered }
}

// Read-only access to the legacy per-team localStorage tiles (see ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX
// in constants.ts). We never write this key; we read any pre-existing CUSTOM value once on mount to
// seed the working state and emit a tombstone, so the localStorage read path can eventually be removed.
function readLegacyOverviewTiles(): AccountsOverviewTile[] | null {
    try {
        const key = Object.keys(window.localStorage).find(
            (k) => k.startsWith(ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX) && k.endsWith('.tiles')
        )
        if (!key) {
            return null
        }
        const parsed = JSON.parse(window.localStorage.getItem(key) ?? 'null')
        if (Array.isArray(parsed) && parsed.length > 0 && !objectsEqual(parsed, DEFAULT_TILES)) {
            return parsed as AccountsOverviewTile[]
        }
    } catch {
        // Inaccessible or malformed localStorage — fall back to defaults.
    }
    return null
}

export const accountsOverviewTilesLogic = kea<accountsOverviewTilesLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsOverviewTilesLogic']),
    connect(() => ({
        values: [
            accountsColumnConfigLogic,
            ['accountsColumnGroups'],
            dataNodeLogic({ key: ACCOUNTS_METRICS_DATA_NODE_KEY, query: {} as DataNode }),
            ['response as accountsResponse', 'responseLoading as accountsResponseLoading'],
        ],
    })),
    actions({
        addTile: (tile: Omit<AccountsOverviewTile, 'id'> & { id?: string }) => ({ tile }),
        updateTile: (id: string, tile: Omit<AccountsOverviewTile, 'id'>) => ({ id, tile }),
        removeTile: (id: string) => ({ id }),
        moveTile: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        setTiles: (tiles: AccountsOverviewTile[]) => ({ tiles }),
        toggleTileSelection: (tile: AccountsOverviewTile) => ({ tile }),
        setTileFilter: (filter: TileFilter | null) => ({ filter }),
        resetTiles: true,
        showEditor: true,
        hideEditor: true,
    }),
    reducers(() => ({
        tiles: [
            DEFAULT_TILES,
            {
                addTile: (
                    state: AccountsOverviewTile[],
                    { tile }: { tile: Omit<AccountsOverviewTile, 'id'> & { id?: string } }
                ) =>
                    state.length >= MAX_ACCOUNTS_OVERVIEW_TILES
                        ? state
                        : [...state, { ...tile, id: tile.id || uuidv4() }],
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
                setTiles: (_state: AccountsOverviewTile[], { tiles }: { tiles: AccountsOverviewTile[] }) => tiles,
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
    listeners(({ actions, values, cache }) => ({
        showEditor: () => {
            cache.tilesSnapshot = values.tiles
        },
        hideEditor: () => {
            const before: AccountsOverviewTile[] | undefined = cache.tilesSnapshot
            cache.tilesSnapshot = undefined
            if (!before) {
                return
            }
            const diff = diffOverviewTiles(before, values.tiles)
            if (diff.changed) {
                posthog.capture(AccountsEvents.OverviewTilesEdited, {
                    tiles_added: diff.added,
                    tiles_removed: diff.removed,
                    tiles_updated: diff.updated,
                    reordered: diff.reordered,
                    tile_count_before: before.length,
                    tile_count_after: values.tiles.length,
                })
            }
        },
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
    afterMount(({ actions }) => {
        // Seed from any legacy localStorage tiles (read-only) and emit a tombstone so we can tell
        // when the localStorage read path is safe to remove. Saved views are the durable store.
        const legacyTiles = readLegacyOverviewTiles()
        if (legacyTiles) {
            actions.setTiles(legacyTiles)
            posthog.capture(AccountsEvents.OverviewTilesLocalStorageRead, { tile_count: legacyTiles.length })
        }
    }),
])
