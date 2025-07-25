import {
    ConversionGoalFilter,
    DataWarehouseNode,
    ExternalDataSourceType,
    MarketingAnalyticsHelperForColumnNames,
    MarketingAnalyticsOrderBy,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'
import { ManualLinkSourceType } from '~/types'

import { NativeSource } from './marketingAnalyticsLogic'
import { googleAdsCostTile } from './marketingCostTile'

export type NativeMarketingSource = Extract<ExternalDataSourceType, 'GoogleAds' | 'MetaAds'>
export type NonNativeMarketingSource = Extract<ExternalDataSourceType, 'BigQuery'>

export const VALID_NATIVE_MARKETING_SOURCES: NativeMarketingSource[] = ['GoogleAds', 'MetaAds']
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

export const NEEDED_FIELDS_FOR_NATIVE_MARKETING_ANALYTICS: Record<NativeMarketingSource, string[]> = {
    GoogleAds: [GOOGLE_ADS_CAMPAIGN_TABLE_NAME, GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME],
    MetaAds: [], // TODO: Add required fields when MetaAds cost tile is implemented in MarketingDashboardMapper
}

export function MarketingDashboardMapper(source: NativeSource): DataWarehouseNode | null {
    switch (source.source.source_type) {
        case 'GoogleAds':
            return googleAdsCostTile(source)
        case 'MetaAds':
            // TODO: Implement MetaAds cost tile when MetaAds support is added
            return null
        default:
            return null
    }
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

export function isDynamicConversionGoalColumn(
    column: string,
    dynamicConversionGoal: ConversionGoalFilter | null
): boolean {
    if (!dynamicConversionGoal) {
        return false
    }
    return (
        column === dynamicConversionGoal.conversion_goal_name ||
        column === `${MarketingAnalyticsHelperForColumnNames.CostPer} ${dynamicConversionGoal.conversion_goal_name}`
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
    const amountPerItem: Record<string, number> = {}
    for (const column of array) {
        amountPerItem[column] = (amountPerItem[column] || 0) + 1
    }

    const newArray: string[] = []
    for (const column of sortedArray) {
        if (array.includes(column) && !newArray.includes(column)) {
            for (let i = 0; i < amountPerItem[column]; i++) {
                newArray.push(column)
            }
        }
    }

    return [...newArray, ...array.filter((column) => !sortedArray.includes(column))]
}
