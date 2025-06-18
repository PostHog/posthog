import { ConversionGoalFilter, CurrencyCode } from '~/queries/schema/schema-general'
import { EntityTypes } from '~/types'

import { MARKETING_ANALYTICS_SCHEMA } from '../../utils'
import { ExternalTable, NativeSource } from './marketingAnalyticsLogic'
import { GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME, GOOGLE_ADS_CAMPAIGN_TABLE_NAME } from './utils'

// Note: most of this logic will live in the backend in the future

const tableColumns = {
    campaign_name: 'campaign_name',
    source_name: 'source_name',
    impressions: 'impressions',
    clicks: 'clicks',
    cost: 'cost',
}

export const unionQueriesString = (
    validNativeSources: NativeSource[],
    validExternalTables: ExternalTable[],
    baseCurrency: CurrencyCode
): string => {
    const nativeQueries = unionNativeQueries(validNativeSources)
    const nonNativeQueries = unionNonNativeQueries(validExternalTables, baseCurrency)
    return [...nativeQueries, ...nonNativeQueries].filter(Boolean).join('\nUNION ALL\n')
}

function unionNativeQueries(validNativeSources: NativeSource[]): string[] {
    const googleAdsUnionNativeQueries = validNativeSources
        .filter((source) => source.source.source_type === 'GoogleAds')
        .map((nativeSource) => {
            const campaignTableData = nativeSource.tables.find(
                (table) => table.name.split('.').pop() === GOOGLE_ADS_CAMPAIGN_TABLE_NAME
            )
            const campaignStatsTableData = nativeSource.tables.find(
                (table) => table.name.split('.').pop() === GOOGLE_ADS_CAMPAIGN_STATS_TABLE_NAME
            )

            if (!campaignTableData || !campaignStatsTableData) {
                return null
            }

            // Use the actual table names from the data
            const campaignTableName = campaignTableData.name
            const campaignStatsTableName = campaignStatsTableData.name

            return `
SELECT
    c.campaign_name as ${tableColumns.campaign_name},
    'google' as ${tableColumns.source_name},
    toFloat(SUM(cs.metrics_impressions)) AS ${tableColumns.impressions},
    toFloat(SUM(cs.metrics_clicks)) AS ${tableColumns.clicks},
    toFloat(SUM(cs.metrics_cost_micros) / 1000000) AS ${tableColumns.cost}
FROM
    ${campaignTableName} c
LEFT JOIN
    ${campaignStatsTableName} cs ON cs.campaign_id = c.campaign_id
WHERE
    cs.segments_date >= '2025-01-01'
GROUP BY
    c.${tableColumns.campaign_name}
`.trim()
        })
        .filter(Boolean) as string[]
    // TODO: add other sources
    return googleAdsUnionNativeQueries
}

function unionNonNativeQueries(validExternalTables: ExternalTable[], baseCurrency: CurrencyCode): string[] {
    const unionNonNativeQueries = validExternalTables
        .map((table) => {
            const tableName = table.name
            const schemaName = table.schema_name
            if (
                !table.source_map ||
                Object.keys(MARKETING_ANALYTICS_SCHEMA)
                    .map((key) => {
                        const field = MARKETING_ANALYTICS_SCHEMA[key]
                        const isRequired = field.required
                        const isDefined = table.source_map?.[key]
                        return isRequired && !isDefined
                    })
                    .some(Boolean)
            ) {
                return null
            }

            // Get source name from schema mapping or fallback
            const sourceNameField =
                table.source_map.utm_source_name || table.source_map.source_name || `'${schemaName}'`
            const campaignNameField = table.source_map.utm_campaign_name || table.source_map.campaign_name

            const costSelect = table.source_map.currency
                ? `toFloat(convertCurrency('${table.source_map.currency}', '${baseCurrency}', toFloat(coalesce(${table.source_map.total_cost}, 0))))`
                : `toFloat(coalesce(${table.source_map.total_cost}, 0))`

            return `
SELECT 
    ${campaignNameField} as ${tableColumns.campaign_name},
    ${sourceNameField} as ${tableColumns.source_name},
    toFloat(coalesce(${table.source_map.impressions || '0'}, 0)) as ${tableColumns.impressions},
    toFloat(coalesce(${table.source_map.clicks || '0'}, 0)) as ${tableColumns.clicks},
    ${costSelect} as ${tableColumns.cost}
FROM ${tableName}
WHERE ${table.source_map.date} >= '2025-01-01'
        `.trim()
        })
        .filter(Boolean)
    return unionNonNativeQueries as string[]
}

function getConversionGoalCTEName(index: number, conversionGoal: ConversionGoalFilter): string {
    return `cg_${index}_${conversionGoal.conversion_goal_name}`.replace(/[^a-zA-Z0-9_]/g, '_')
}

export function generateGoalConversionCTEs(conversionGoals: ConversionGoalFilter[]): string {
    // Generate CTEs for all conversion goals
    const conversionGoalCTEs = conversionGoals
        .map((conversionGoal, index) => {
            const propertyName = conversionGoal.type === EntityTypes.EVENTS ? 'properties.' : ''
            // Sanitize the CTE name to be a valid SQL identifier
            const cteName = getConversionGoalCTEName(index, conversionGoal)
            return `
${cteName} AS (
SELECT 
    ${propertyName}${conversionGoal.schema.utm_campaign_name} as ${tableColumns.campaign_name},
    ${propertyName}${conversionGoal.schema.utm_source_name} as ${tableColumns.source_name},
    count(*) as conversion_${index}
FROM ${getConversionGoalTable(conversionGoal)} 
WHERE ${
                conversionGoal.type === EntityTypes.EVENTS && conversionGoal.id
                    ? `event = ${typeof conversionGoal.id === 'string' ? `'${conversionGoal.id}'` : conversionGoal.id}`
                    : '1=1'
            }
    AND ${tableColumns.campaign_name} IS NOT NULL
    AND ${tableColumns.campaign_name} != ''
    AND ${tableColumns.source_name} IS NOT NULL
    AND ${tableColumns.source_name} != ''
GROUP BY ${tableColumns.campaign_name}, ${tableColumns.source_name}
        )`
        })
        .join(',\n')
    return conversionGoalCTEs
}

export function generateGoalConversionJoins(conversionGoals: ConversionGoalFilter[]): string {
    return conversionGoals.length > 0
        ? conversionGoals
              .map((conversionGoal, index) => {
                  const cteName = getConversionGoalCTEName(index, conversionGoal)
                  return `
LEFT JOIN ${cteName} cg_${index} ON cc.${tableColumns.campaign_name} = cg_${index}.${tableColumns.campaign_name} 
    AND cc.${tableColumns.source_name} = cg_${index}.${tableColumns.source_name}`
              })
              .join('\n                    ')
        : ''
}

export function generateGoalConversionSelects(conversionGoals: ConversionGoalFilter[]): string {
    return conversionGoals.length > 0
        ? conversionGoals
              .map((conversionGoal, index) => [
                  `cg_${index}.conversion_${index} as "${conversionGoal.conversion_goal_name}"`,
                  `round(cc.total_cost / nullif(cg_${index}.conversion_${index}, 0), 2) as "Cost per ${conversionGoal.conversion_goal_name}"`,
              ])
              .flat()
              .join(',\n                        ')
        : ''
}

export function generateWithClause(unionQueries: string, conversionGoalCTEs: string): string {
    return `
WITH campaign_costs AS (
SELECT 
    ${tableColumns.campaign_name},
    ${tableColumns.source_name},
    sum(${tableColumns.cost}) as total_cost,
    sum(${tableColumns.clicks}) as total_clicks,
    sum(${tableColumns.impressions}) as total_impressions
FROM (
    ${unionQueries}
)
GROUP BY ${tableColumns.campaign_name}, ${tableColumns.source_name}
)
${conversionGoalCTEs ? `, ${conversionGoalCTEs}` : ''}`
}

export function generateSelect(withClause: string, conversionColumns: string, conversionJoins: string): string {
    return `
${withClause}
SELECT 
    cc.campaign_name as "Campaign",
    cc.source_name as "Source",
    round(cc.total_cost, 2) as "Total Cost",
    cc.total_clicks as "Total Clicks", 
    cc.total_impressions as "Total Impressions",
    round(cc.total_cost / nullif(cc.total_clicks, 0), 2) as "Cost per Click",
    round(cc.total_clicks / nullif(cc.total_impressions, 0) * 100, 2) as "CTR"${
        conversionColumns ? `,\n                        ${conversionColumns}` : ''
    }
FROM campaign_costs cc
${conversionJoins}
ORDER BY cc.total_cost DESC
LIMIT 20
`.trim()
}

function getConversionGoalTable(conversionGoal: ConversionGoalFilter): string {
    if (!conversionGoal.name) {
        return 'events'
    }
    switch (conversionGoal.type) {
        case EntityTypes.EVENTS:
            return 'events'
        case EntityTypes.DATA_WAREHOUSE:
            return conversionGoal.name
        default:
            throw new Error(`Unsupported conversion goal type: ${conversionGoal.type}`)
    }
}
