import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { isUUIDLike } from 'lib/utils/guards'
import { objectsEqual } from 'lib/utils/objects'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AccountsTableAggregation,
    AccountsTableCustomPropertyFilter,
    AccountsTableCustomPropertyOperator,
    AccountsTableMetric,
    AccountsTableQueryResponse,
    AccountsTableThresholdOperator,
    DataNode,
} from '~/queries/schema/schema-general'

import type { CustomPropertyDisplayTypeEnumApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type {
    ErrorTrackingQueryResponse,
    HogQLAutocompleteResponse,
    HogQLMetadataResponse,
    HogQLQueryResponse,
    HogQueryResponse,
    LogAttributesQueryResponse,
    LogValuesQueryResponse,
    MetricsQueryResponse,
    SessionsQueryResponse,
    TraceSpansAggregationQueryResponse,
    TraceSpansAttributeBreakdownQueryResponse,
    TraceSpansQueryResponse,
} from '../../../../../frontend/src/queries/schema/schema-general'
import { ACCOUNTS_METRICS_DATA_NODE_KEY } from '../../constants'
import { isNumericDisplayType } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import { AccountColumnGroup, AccountColumnOption, accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import {
    ACCOUNTS_OVERVIEW_LEGACY_TILES_PREFIX,
    AccountsEvents,
    AccountsOverviewThresholdOperator,
    DEFAULT_TILES,
    MAX_ACCOUNTS_OVERVIEW_TILES,
    NUMERIC_FIELD_TYPES,
} from './constants'

// Single-column scalar aggregations share one saved-view shape and support an
// optional scale multiplier, such as annualizing monthly recurring revenue.
export const COLUMN_AGGREGATE_TYPES = ['sum', 'avg', 'min', 'max', 'median'] as const
export type ColumnAggregateType = (typeof COLUMN_AGGREGATE_TYPES)[number]

export type AccountsOverviewTileMetric =
    | { type: 'count' }
    | { type: ColumnAggregateType; columnExpression: string; columnLabel: string; scale?: number }
    | {
          type: 'count_threshold'
          columnExpression: string
          columnLabel: string
          operator: AccountsOverviewThresholdOperator
          value: number
      }

export type AccountsOverviewTileMetricType = AccountsOverviewTileMetric['type']

// Per-tile value display format. A subset of OverviewGrid's WebAnalyticsItemKind
// (we omit `duration_s`, no account metric is a duration), so `format` maps 1:1
// to the render `kind`. `currency` uses the team's base currency; `percentage`
// treats the value as already in percent units (85 → "85%").
export const TILE_VALUE_FORMATS = ['unit', 'currency', 'percentage'] as const
export type TileValueFormat = (typeof TILE_VALUE_FORMATS)[number]

export function isColumnAggregateMetric(
    metric: AccountsOverviewTileMetric
): metric is Extract<AccountsOverviewTileMetric, { type: ColumnAggregateType }> {
    return (COLUMN_AGGREGATE_TYPES as readonly string[]).includes(metric.type)
}

export interface AccountsOverviewTile {
    id: string
    label: string
    metric: AccountsOverviewTileMetric
    // Custom subtitle; empty/whitespace/undefined falls back to the auto-derived caption.
    caption?: string
    // Value display format; undefined renders as a plain unit.
    format?: TileValueFormat
}

export interface TileFilter {
    tileId: string
    filter: AccountsTableCustomPropertyFilter
}

// Saved column expressions include an alias for table rendering, while saved
// tile expressions identify the underlying typed custom property.
export function stripColumnAlias(expression: string): string {
    return expression.replace(/\s+AS\s+[A-Za-z_][\w]*\s*$/i, '').trim()
}

export function isNumericColumnType(type: string | undefined): boolean {
    if (!type) {
        return false
    }
    // Account fields carry schema types, while custom properties carry display types.
    return NUMERIC_FIELD_TYPES.has(type) || isNumericDisplayType(type as CustomPropertyDisplayTypeEnumApi)
}

export function numericColumnOptions(groups: AccountColumnGroup[]): AccountColumnOption[] {
    return groups.flatMap((group) =>
        group.options
            .filter((option) => isNumericColumnType(option.type))
            .map((option) => {
                const expression = stripColumnAlias(option.expression)
                return {
                    ...option,
                    // Preserve the existing saved-tile expression shape while execution uses a typed metric.
                    expression: group.key === 'custom_properties' ? `toFloatOrNull(${expression})` : expression,
                }
            })
    )
}

export function scaleSuffix(scale: number | undefined): string {
    return scale === undefined || !Number.isFinite(scale) || scale === 1 ? '' : ` × ${scale}`
}

const CUSTOM_PROPERTY_METRIC_REGEX = /^(?:toFloatOrNull\()?accounts\.custom_properties\.values\.`([0-9a-fA-F-]+)`\)?$/

function metricDefinitionId(columnExpression: string): string | null {
    const definitionId = stripColumnAlias(columnExpression).match(CUSTOM_PROPERTY_METRIC_REGEX)?.[1]
    return definitionId && isUUIDLike(definitionId) ? definitionId : null
}

export function tileQueryMetric(tile: AccountsOverviewTile): AccountsTableMetric | null {
    if (tile.metric.type === 'count') {
        return { kind: 'count' }
    }
    const definitionId = metricDefinitionId(tile.metric.columnExpression)
    if (!definitionId) {
        return null
    }
    const column = { kind: 'custom_property' as const, definitionId }
    if (tile.metric.type === 'count_threshold') {
        const operator = {
            '>': AccountsTableThresholdOperator.GreaterThan,
            '>=': AccountsTableThresholdOperator.GreaterThanOrEqual,
            '<': AccountsTableThresholdOperator.LessThan,
            '<=': AccountsTableThresholdOperator.LessThanOrEqual,
            '=': AccountsTableThresholdOperator.Equal,
            '!=': AccountsTableThresholdOperator.NotEqual,
        }[tile.metric.operator]
        return operator ? { kind: 'count_threshold', column, operator, value: tile.metric.value } : null
    }
    const aggregation = {
        sum: AccountsTableAggregation.Sum,
        avg: AccountsTableAggregation.Average,
        min: AccountsTableAggregation.Minimum,
        max: AccountsTableAggregation.Maximum,
        median: AccountsTableAggregation.Median,
    }[tile.metric.type]
    return {
        kind: 'aggregate',
        aggregation,
        column,
        scale: Number.isFinite(tile.metric.scale) ? tile.metric.scale : undefined,
    }
}

// The auto-derived subtitle for a tile, from its metric. `count` has none.
export function autoCaption(tile: AccountsOverviewTile): string | undefined {
    const { metric } = tile
    switch (metric.type) {
        case 'count':
            return undefined
        case 'count_threshold':
            return `${metric.columnLabel} ${metric.operator} ${metric.value}`
        default:
            // sum | avg | min | max | median: the metric type reads as the aggregation verb.
            return `${metric.type} of ${metric.columnLabel}${scaleSuffix(metric.scale)}`
    }
}

// The subtitle shown on a tile: the user's custom caption when set, else the
// auto-derived one. A whitespace-only caption is treated as unset.
export function tileCaption(tile: AccountsOverviewTile): string | undefined {
    const custom = tile.caption?.trim()
    return custom ? custom : autoCaption(tile)
}

export function tileToRowFilter(tile: AccountsOverviewTile): AccountsTableCustomPropertyFilter | null {
    const metric = tileQueryMetric(tile)
    if (!metric || metric.kind !== 'count_threshold') {
        return null
    }
    const operator = {
        [AccountsTableThresholdOperator.GreaterThan]: AccountsTableCustomPropertyOperator.GreaterThan,
        [AccountsTableThresholdOperator.GreaterThanOrEqual]: AccountsTableCustomPropertyOperator.GreaterThanOrEqual,
        [AccountsTableThresholdOperator.LessThan]: AccountsTableCustomPropertyOperator.LessThan,
        [AccountsTableThresholdOperator.LessThanOrEqual]: AccountsTableCustomPropertyOperator.LessThanOrEqual,
        [AccountsTableThresholdOperator.Equal]: AccountsTableCustomPropertyOperator.Exact,
        [AccountsTableThresholdOperator.NotEqual]: AccountsTableCustomPropertyOperator.IsNot,
    }[metric.operator]
    return {
        kind: 'custom_property',
        definitionId: metric.column.definitionId,
        operator,
        values: [metric.value],
    }
}

export function isTileClickable(tile: AccountsOverviewTile): boolean {
    return tileToRowFilter(tile) !== null
}

export function tileFilterFor(tile: AccountsOverviewTile): TileFilter | null {
    const filter = tileToRowFilter(tile)
    return filter ? { tileId: tile.id, filter } : null
}

function readNumeric(raw: unknown): number | null {
    if (raw === null || raw === undefined) {
        return null
    }
    const numeric = typeof raw === 'number' ? raw : Number(raw)
    return Number.isFinite(numeric) ? numeric : null
}

export function parseTileValues(
    response: AccountsTableQueryResponse | null,
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
        return numericExpressions.has(tile.metric.columnExpression) && tileQueryMetric(tile) !== null
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsOverviewTilesLogicValues {
    accountsColumnGroups: AccountColumnGroup[] // accountsColumnConfigLogic
    accountsResponse:
        | ErrorTrackingQueryResponse
        | HogQLAutocompleteResponse
        | HogQLMetadataResponse
        | HogQLQueryResponse<any[]>
        | HogQueryResponse
        | LogAttributesQueryResponse
        | LogValuesQueryResponse
        | MetricsQueryResponse
        | Record<string, any>
        | SessionsQueryResponse
        | TraceSpansAggregationQueryResponse
        | TraceSpansAttributeBreakdownQueryResponse
        | TraceSpansQueryResponse
        | null // dataNodeLogic
    accountsResponseLoading: boolean // dataNodeLogic
    editorVisible: boolean
    metrics: AccountsTableMetric[]
    numericColumnExpressions: Set<string>
    numericColumns: AccountColumnOption[]
    reconciledTiles: AccountsOverviewTile[]
    selectedTileId: string | null
    tileFilter: TileFilter | null
    tileValues: Record<string, number | null>
    tiles: AccountsOverviewTile[]
    tilesLoading: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsOverviewTilesLogicActions {
    addTile: (
        tile: Omit<AccountsOverviewTile, 'id'> & {
            id?: string
        }
    ) => {
        tile: Omit<AccountsOverviewTile, 'id'> & {
            id?: string | undefined
        }
    }
    hideEditor: () => {
        value: true
    }
    moveTile: (
        oldIndex: number,
        newIndex: number
    ) => {
        newIndex: number
        oldIndex: number
    }
    removeTile: (id: string) => {
        id: string
    }
    resetTiles: () => {
        value: true
    }
    setTileFilter: (filter: TileFilter | null) => {
        filter: TileFilter | null
    }
    setTiles: (tiles: AccountsOverviewTile[]) => {
        tiles: AccountsOverviewTile[]
    }
    showEditor: () => {
        value: true
    }
    toggleTileSelection: (tile: AccountsOverviewTile) => {
        tile: AccountsOverviewTile
    }
    updateTile: (
        id: string,
        tile: Omit<AccountsOverviewTile, 'id'>
    ) => {
        id: string
        tile: Omit<AccountsOverviewTile, 'id'>
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsOverviewTilesLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        numericColumns: (accountsColumnGroups: AccountColumnGroup[]) => AccountColumnOption[]
        numericColumnExpressions: (numericColumns: AccountColumnOption[]) => Set<string>
        reconciledTiles: (
            tiles: AccountsOverviewTile[],
            numericColumnExpressions: Set<string>
        ) => AccountsOverviewTile[]
        metrics: (reconciledTiles: AccountsOverviewTile[]) => AccountsTableMetric[]
        tileValues: (
            accountsResponse:
                | ErrorTrackingQueryResponse
                | HogQLAutocompleteResponse
                | HogQLMetadataResponse
                | HogQLQueryResponse<any[]>
                | HogQueryResponse
                | LogAttributesQueryResponse
                | LogValuesQueryResponse
                | MetricsQueryResponse
                | Record<string, any>
                | SessionsQueryResponse
                | TraceSpansAggregationQueryResponse
                | TraceSpansAttributeBreakdownQueryResponse
                | TraceSpansQueryResponse
                | null,
            reconciledTiles: AccountsOverviewTile[]
        ) => Record<string, number | null>
        tilesLoading: (accountsResponseLoading: boolean) => boolean
        selectedTileId: (tileFilter: TileFilter | null) => string | null
    }
}

export type accountsOverviewTilesLogicType = MakeLogicType<
    accountsOverviewTilesLogicValues,
    accountsOverviewTilesLogicActions,
    Record<string, any>,
    accountsOverviewTilesLogicMeta
>

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
            (tiles: AccountsOverviewTile[]): AccountsTableMetric[] =>
                tiles.map(tileQueryMetric).filter((metric): metric is AccountsTableMetric => metric !== null),
        ],
        tileValues: [
            (s) => [s.accountsResponse, s.reconciledTiles],
            (
                response: AccountsTableQueryResponse | null,
                tiles: AccountsOverviewTile[]
            ): Record<string, number | null> => parseTileValues(response, tiles),
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
