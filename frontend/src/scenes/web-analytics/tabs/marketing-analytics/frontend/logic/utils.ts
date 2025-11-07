import {
    AttributionMode,
    ConversionGoalFilter,
    DataWarehouseNode,
    ExternalDataSourceType,
    MarketingAnalyticsColumnsSchemaNames,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsOrderBy,
    MarketingAnalyticsTableQuery,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ManualLinkSourceType, PropertyMathType } from '~/types'

import { NativeSource } from './marketingAnalyticsLogic'

export type NativeMarketingSource = Extract<
    ExternalDataSourceType,
    'GoogleAds' | 'RedditAds' | 'LinkedinAds' | 'MetaAds' | 'TikTokAds'
>
export type NonNativeMarketingSource = Extract<ExternalDataSourceType, 'BigQuery'>

export const VALID_NATIVE_MARKETING_SOURCES: NativeMarketingSource[] = [
    'GoogleAds',
    'RedditAds',
    'LinkedinAds',
    'MetaAds',
    'TikTokAds',
]

export const VALID_NON_NATIVE_MARKETING_SOURCES: NonNativeMarketingSource[] = ['BigQuery']
export const VALID_SELF_MANAGED_MARKETING_SOURCES: ManualLinkSourceType[] = [
    'aws',
    'google-cloud',
    'cloudflare-r2',
    'azure',
]

export const MAX_ITEMS_TO_SHOW = 3

export const GOOGLE_ADS_CAMPAIGN_TABLE_NAME = 'campaign'
export const GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME = 'campaign_stats'

export const LINKEDIN_ADS_CAMPAIGN_TABLE_NAME = 'campaigns'
export const LINKEDIN_ADS_CAMPAIGN_STATS_TABLE_NAME = 'campaign_stats'

export const REDDIT_ADS_CAMPAIGN_TABLE_NAME = 'campaigns'
export const REDDIT_ADS_CAMPAIGN_STATS_TABLE_NAME = 'campaign_report'

export const META_ADS_CAMPAIGN_TABLE_NAME = 'campaigns'
export const META_ADS_CAMPAIGN_STATS_TABLE_NAME = 'campaign_stats'

export const TIKTOK_ADS_CAMPAIGN_TABLE_NAME = 'campaigns'
export const TIKTOK_ADS_CAMPAIGN_REPORT_TABLE_NAME = 'campaign_report'

export const NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS: Record<NativeMarketingSource, string[]> = {
    GoogleAds: [GOOGLE_ADS_CAMPAIGN_TABLE_NAME, GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME],
    LinkedinAds: [LINKEDIN_ADS_CAMPAIGN_TABLE_NAME, LINKEDIN_ADS_CAMPAIGN_STATS_TABLE_NAME],
    RedditAds: [REDDIT_ADS_CAMPAIGN_TABLE_NAME, REDDIT_ADS_CAMPAIGN_STATS_TABLE_NAME],
    MetaAds: [META_ADS_CAMPAIGN_TABLE_NAME, META_ADS_CAMPAIGN_STATS_TABLE_NAME],
    TikTokAds: [TIKTOK_ADS_CAMPAIGN_TABLE_NAME, TIKTOK_ADS_CAMPAIGN_REPORT_TABLE_NAME],
}

export const MAX_ATTRIBUTION_WINDOW_DAYS = 90
export const MIN_ATTRIBUTION_WINDOW_DAYS = 1
export const DEFAULT_ATTRIBUTION_WINDOW_DAYS = 90
export const DEFAULT_ATTRIBUTION_MODE = AttributionMode.LastTouch

export const ATTRIBUTION_WINDOW_OPTIONS = [
    { value: 1, label: '1 day' },
    { value: 7, label: '1 week (7 days)' },
    { value: 14, label: '2 weeks (14 days)' },
    { value: 30, label: '1 month (30 days)' },
    { value: 90, label: '3 months (90 days)' },
    { value: 'custom', label: 'Custom' },
]

export function MarketingDashboardMapper(
    source: NativeSource,
    tileColumnSelection: validColumnsForTiles,
    baseCurrency: string
): DataWarehouseNode | null {
    return createMarketingTile(source, tileColumnSelection, baseCurrency)
}

export const COST_MICROS_MULTIPLIER = 1 / 1000000

/**
 * Generates a unique name by adding a numeric suffix if the base name already exists in the given list.
 * @param baseName The desired base name
 * @param existingNames Array of names that already exist
 * @returns A unique name, either the original or with a numeric suffix like "(1)", "(2)", etc.
 */
export function generateUniqueName(baseName: string, existingNames: string[]): string {
    if (!existingNames.includes(baseName)) {
        return baseName
    }

    // Find the next available number suffix
    let counter = 1
    let newName = `${baseName} (${counter})`

    while (existingNames.includes(newName)) {
        counter++
        newName = `${baseName} (${counter})`
    }

    return newName
}

export function isDraftConversionGoalColumn(column: string, draftConversionGoal: ConversionGoalFilter | null): boolean {
    if (!draftConversionGoal) {
        return false
    }
    return (
        column === draftConversionGoal.conversion_goal_name ||
        column === `${MarketingAnalyticsHelperForColumnNames.CostPer} ${draftConversionGoal.conversion_goal_name}`
    )
}

/**
 * Get the order by for the query and ensure that the order by is in the columns
 * @param query - The query to get the order by for
 * @param columns - The columns to include in the order by
 * @returns The order by for the query
 */
export function getOrderBy(
    query: MarketingAnalyticsTableQuery | undefined,
    columns: string[]
): MarketingAnalyticsOrderBy[] {
    const orderBy = (query?.orderBy || []).filter((column) => {
        const columnName = column[0]
        return columns.includes(columnName)
    })
    return orderBy
}

/**
 * Order the array by the preference
 * @param array - The array to order
 * @param preference - The preference to order the array by
 * @returns The ordered array preserving the order of the items in the original array
 * This is used to prioritize pinned columns over the rest of the columns but preserving
 * the order of the items in the original array.
 * example:
 * orderArrayByPreference(['a', 'b', 'c'], ['c', 'b']) -> ['b', 'c', 'a']
 */
export function orderArrayByPreference(array: string[], preference: string[]): string[] {
    return [
        ...array.filter((column) => preference.includes(column)),
        ...array.filter((column) => !preference.includes(column)),
    ]
}

/**
 * Get the sorted columns by the array
 * @param array - The array to get the sorted columns for
 * @param sortedArray - The array to sort the columns by
 * @returns The sorted columns by the sorted array preference. This is used
 * to sort the columns by the default order of the columns.
 * example:
 * getSortedColumnsByArray(['a', 'b', 'c', 'c'], ['c', 'b', 'c']) -> ['c', 'c', 'b', 'a']
 */
export function getSortedColumnsByArray(array: string[], sortedArray: string[]): string[] {
    const amountPerItem = new Map<string, number>()
    for (const column of array) {
        amountPerItem.set(column, (amountPerItem.get(column) ?? 0) + 1)
    }

    const newArray: string[] = []
    const added = new Set<string>()

    for (const column of sortedArray) {
        if (amountPerItem.has(column) && !added.has(column)) {
            const count = amountPerItem.get(column)!
            newArray.push(...Array(count).fill(column))
            added.add(column)
        }
    }

    for (const column of array) {
        if (!sortedArray.includes(column)) {
            newArray.push(column)
        }
    }

    return newArray
}

export function createMarketingAnalyticsOrderBy(
    column: string,
    direction: 'ASC' | 'DESC'
): MarketingAnalyticsOrderBy[] {
    return [[column, direction]]
}
export type validColumnsForTiles = Extract<
    MarketingAnalyticsColumnsSchemaNames,
    'cost' | 'impressions' | 'clicks' | 'reported_conversion'
>

interface ColumnConfig {
    name: string
    type: string
    needsDivision: boolean
}

interface SourceColumnMappings {
    cost: string
    impressions: string
    clicks: string
    reportedConversion: string
    costNeedsDivision?: boolean
    currencyColumn?: string
    fallbackCurrency?: string
}

interface SourceTileConfig {
    statsTableName: string
    displayName: string
    idField: string
    timestampField: string
    columnMappings: SourceColumnMappings
    specialConversionLogic?: (
        _table: any,
        tileColumnSelection: validColumnsForTiles
    ) => Partial<DataWarehouseNode> | null
}

const sourceTileConfigs: Record<NativeMarketingSource, SourceTileConfig> = {
    GoogleAds: {
        statsTableName: 'campaign_stats',
        displayName: 'google',
        idField: 'id',
        timestampField: 'segments_date',
        columnMappings: {
            cost: 'metrics_cost_micros',
            impressions: 'metrics_impressions',
            clicks: 'metrics_clicks',
            reportedConversion: 'metrics_conversions',
            costNeedsDivision: true,
            currencyColumn: 'customer_currency_code',
            fallbackCurrency: 'USD',
        },
    },
    RedditAds: {
        statsTableName: 'campaign_report',
        displayName: 'reddit',
        idField: 'campaign_id',
        timestampField: 'date',
        columnMappings: {
            cost: 'spend',
            impressions: 'impressions',
            clicks: 'clicks',
            reportedConversion: 'conversion_purchase_total_items',
            costNeedsDivision: true,
            currencyColumn: 'currency',
        },
        specialConversionLogic: (_table, tileColumnSelection) => {
            if (tileColumnSelection === MarketingAnalyticsColumnsSchemaNames.ReportedConversion) {
                return {
                    math: 'hogql' as any,
                    math_hogql:
                        'SUM(toFloat(conversion_signup_total_value) + toFloat(conversion_purchase_total_items))',
                }
            }
            return null
        },
    },
    LinkedinAds: {
        statsTableName: 'campaign_stats',
        displayName: 'linkedin',
        idField: 'id',
        timestampField: 'date_start',
        columnMappings: {
            cost: 'cost_in_usd',
            impressions: 'impressions',
            clicks: 'clicks',
            reportedConversion: 'external_website_conversions',
            fallbackCurrency: 'USD',
        },
    },
    MetaAds: {
        statsTableName: 'campaign_stats',
        displayName: 'meta',
        idField: 'campaign_id',
        timestampField: 'date_stop',
        columnMappings: {
            cost: 'spend',
            impressions: 'impressions',
            clicks: 'clicks',
            reportedConversion: 'conversions',
            currencyColumn: 'account_currency',
        },
        specialConversionLogic: (table, tileColumnSelection) => {
            if (tileColumnSelection === MarketingAnalyticsColumnsSchemaNames.ReportedConversion) {
                // If meta does not return conversions it won't be in the table.fields.
                const hasConversionsColumn = table.fields && 'conversions' in table.fields
                if (hasConversionsColumn) {
                    return {
                        math: 'hogql' as any,
                        math_hogql: 'SUM(toFloat(conversions))',
                    }
                }
                return {
                    math: 'hogql' as any,
                    math_hogql: '0',
                }
            }
            return null
        },
    },
    TikTokAds: {
        statsTableName: 'campaign_report',
        displayName: 'tiktok',
        idField: 'campaign_id',
        timestampField: 'stat_time_day',
        columnMappings: {
            cost: 'spend',
            impressions: 'impressions',
            clicks: 'clicks',
            reportedConversion: 'conversion',
            currencyColumn: 'currency',
        },
        specialConversionLogic: (table, tileColumnSelection) => {
            if (tileColumnSelection === MarketingAnalyticsColumnsSchemaNames.ReportedConversion) {
                // If TikTok does not return conversion it won't be in the table.fields.
                const hasConversionsColumn = table.fields && 'conversion' in table.fields
                if (hasConversionsColumn) {
                    return {
                        math: 'hogql' as any,
                        math_hogql: 'SUM(toFloat(conversion))',
                    }
                }
                return {
                    math: 'hogql' as any,
                    math_hogql: '0',
                }
            }
            return null
        },
    },
}

function createColumnConfig(columnName: string, type: 'float' | 'integer', needsDivision = false): ColumnConfig {
    return { name: columnName, type, needsDivision }
}

function buildSourceConfig(mappings: SourceColumnMappings): {
    columns: { [key in validColumnsForTiles]: ColumnConfig }
} {
    return {
        columns: {
            [MarketingAnalyticsColumnsSchemaNames.Cost]: createColumnConfig(
                mappings.cost,
                'float',
                mappings.costNeedsDivision ?? false
            ),
            [MarketingAnalyticsColumnsSchemaNames.Impressions]: createColumnConfig(mappings.impressions, 'integer'),
            [MarketingAnalyticsColumnsSchemaNames.Clicks]: createColumnConfig(mappings.clicks, 'integer'),
            [MarketingAnalyticsColumnsSchemaNames.ReportedConversion]: createColumnConfig(
                mappings.reportedConversion,
                'integer'
            ),
        },
    }
}

export const columnTileConfig: {
    [key in NativeMarketingSource]: {
        columns: {
            [key in validColumnsForTiles]: ColumnConfig
        }
    }
} = Object.fromEntries(
    VALID_NATIVE_MARKETING_SOURCES.map((source) => [
        source,
        buildSourceConfig(sourceTileConfigs[source].columnMappings),
    ])
) as any

export function createMarketingTile(
    source: NativeSource,
    tileColumnSelection: validColumnsForTiles,
    baseCurrency: string
): DataWarehouseNode | null {
    const sourceType = source.source.source_type as NativeMarketingSource
    const config = sourceTileConfigs[sourceType]

    if (!config) {
        return null
    }

    const table = source.tables.find((t) => t.name.split('.').pop() === config.statsTableName)
    if (!table) {
        return null
    }

    const column = columnTileConfig[sourceType].columns[tileColumnSelection]
    if (!column) {
        return null
    }

    // Check for special conversion logic first
    if (config.specialConversionLogic) {
        const specialLogic = config.specialConversionLogic(table, tileColumnSelection)
        if (specialLogic) {
            return {
                kind: NodeKind.DataWarehouseNode,
                id: table.id,
                name: config.displayName,
                custom_name: `${table.name} ${tileColumnSelection}`,
                id_field: config.idField,
                distinct_id_field: config.idField,
                timestamp_field: config.timestampField,
                table_name: table.name,
                ...specialLogic,
            }
        }
    }

    if (tileColumnSelection === MarketingAnalyticsColumnsSchemaNames.Cost) {
        const mappings = config.columnMappings
        const costColumn = mappings.cost
        const currencyColumn = mappings.currencyColumn
        const fallbackCurrency = mappings.fallbackCurrency
        const needsDivision = mappings.costNeedsDivision

        let costExpr = needsDivision ? `toFloat(${costColumn} / 1000000)` : `toFloat(${costColumn})`

        let mathHogql: string

        const hasCurrencyColumn = currencyColumn && table.fields && currencyColumn in table.fields

        if (hasCurrencyColumn) {
            mathHogql = `SUM(toFloat(convertCurrency(coalesce(${currencyColumn}, '${baseCurrency}'), '${baseCurrency}', ${costExpr})))`
        } else if (fallbackCurrency) {
            mathHogql = `toFloat(convertCurrency('${fallbackCurrency}', '${baseCurrency}', SUM(${costExpr})))`
        } else {
            mathHogql = `SUM(${costExpr})`
        }

        return {
            kind: NodeKind.DataWarehouseNode,
            id: table.id,
            name: config.displayName,
            custom_name: `${table.name} ${tileColumnSelection}`,
            id_field: config.idField,
            distinct_id_field: config.idField,
            timestamp_field: config.timestampField,
            table_name: table.name,
            math: 'hogql' as any,
            math_hogql: mathHogql,
        }
    }

    // Default tile configuration for non-cost columns
    return {
        kind: NodeKind.DataWarehouseNode,
        id: table.id,
        name: config.displayName,
        custom_name: `${table.name} ${tileColumnSelection}`,
        id_field: config.idField,
        distinct_id_field: config.idField,
        timestamp_field: config.timestampField,
        table_name: table.name,
        math: PropertyMathType.Sum,
        math_property: column.name,
    }
}
