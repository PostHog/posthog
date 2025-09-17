import { CurrencyCode, DataWarehouseNode, MARKETING_ANALYTICS_SCHEMA, NodeKind } from '~/queries/schema/schema-general'
import { PropertyMathType } from '~/types'

import { ExternalTable, NativeSource } from './marketingAnalyticsLogic'
import { columnTileConfig, validColumnsForTiles } from './utils'
import {
    COST_MICROS_MULTIPLIER,
    GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME,
    LINKEDIN_ADS_CAMPAIGN_STATS_TABLE_NAME,
    META_ADS_CAMPAIGN_STATS_TABLE_NAME,
    REDDIT_ADS_CAMPAIGN_STATS_TABLE_NAME,
} from './utils'

export const googleAdsCostTile = (
    source: NativeSource,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    const table = source.tables.find((t) => t.name.split('.').pop() === GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME)
    if (!table) {
        return null
    }
    const column = columnTileConfig.GoogleAds.columns[tileColumnSelection]
    if (!column) {
        return null
    }
    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: 'google',
        custom_name: `${table.name} ${tileColumnSelection}`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: 'segments_date',
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: column.name,
        ...(MARKETING_ANALYTICS_SCHEMA[tileColumnSelection].isCurrency
            ? { math_property_revenue_currency: { static: CurrencyCode.USD } }
            : {}),
        ...(column.needsDivision ? { math_multiplier: COST_MICROS_MULTIPLIER } : {}),
    }
}
export const linkedinAdsCostTile = (
    source: NativeSource,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    const table = source.tables.find((t) => t.name.split('.').pop() === LINKEDIN_ADS_CAMPAIGN_STATS_TABLE_NAME)
    if (!table) {
        return null
    }
    const column = columnTileConfig.LinkedinAds.columns[tileColumnSelection]
    if (!column) {
        return null
    }
    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: 'linkedin',
        custom_name: `${table.name} ${tileColumnSelection}`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: 'date_start',
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: column.name,
        ...(MARKETING_ANALYTICS_SCHEMA[tileColumnSelection].isCurrency
            ? { math_property_revenue_currency: { static: CurrencyCode.USD } }
            : {}),
        ...(column.needsDivision ? { math_multiplier: COST_MICROS_MULTIPLIER } : {}),
    }
}

export const redditAdsCostTile = (
    source: NativeSource,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    const table = source.tables.find((t) => t.name.split('.').pop() === REDDIT_ADS_CAMPAIGN_STATS_TABLE_NAME)
    if (!table) {
        return null
    }

    const column = columnTileConfig.RedditAds.columns[tileColumnSelection]
    if (!column) {
        return null
    }

    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: 'reddit',
        custom_name: `${table.name} ${tileColumnSelection}`,
        id_field: 'campaign_id',
        distinct_id_field: 'campaign_id',
        timestamp_field: 'date',
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: column.name,
        ...(MARKETING_ANALYTICS_SCHEMA[tileColumnSelection].isCurrency
            ? { math_property_revenue_currency: { static: CurrencyCode.USD } }
            : {}),
        ...(column.needsDivision ? { math_multiplier: COST_MICROS_MULTIPLIER } : {}),
    }
}

export const metaAdsCostTile = (
    source: NativeSource,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    const table = source.tables.find((t) => t.name.split('.').pop() === META_ADS_CAMPAIGN_STATS_TABLE_NAME)
    if (!table) {
        return null
    }

    const column = columnTileConfig.RedditAds.columns[tileColumnSelection]
    if (!column) {
        return null
    }

    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: 'reddit',
        custom_name: `${table.name} ${tileColumnSelection}`,
        id_field: 'campaign_id',
        distinct_id_field: 'campaign_id',
        timestamp_field: 'date_stop',
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: column.name,
        ...(MARKETING_ANALYTICS_SCHEMA[tileColumnSelection].isCurrency
            ? { math_property_revenue_currency: { static: CurrencyCode.USD } }
            : {}),
        ...(column.needsDivision ? { math_multiplier: COST_MICROS_MULTIPLIER } : {}),
    }
}

export const externalAdsCostTile = (
    table: ExternalTable,
    baseCurrency: string,
    tileColumnSelection: validColumnsForTiles
): DataWarehouseNode | null => {
    if (!table.source_map || !table.source_map.date || !table.source_map.cost) {
        return null
    }

    const column = table.source_map[tileColumnSelection]
    if (!column) {
        return null
    }
    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: table.schema_name,
        custom_name: `${table.schema_name} ${tileColumnSelection}`,
        id_field: 'id',
        distinct_id_field: 'id',
        timestamp_field: table.source_map.date,
        table_name: table.name,
        dw_source_type: table.dw_source_type,
        math: PropertyMathType.Sum,
        math_property: column,
        math_property_revenue_currency: {
            static: (table.source_map.currency || baseCurrency) as CurrencyCode,
        },
    }
}
