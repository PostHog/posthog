import {
    DataTableNode,
    MARKETING_ANALYTICS_DRILL_DOWN_CONFIG,
    MarketingAnalyticsBaseColumns,
    MarketingAnalyticsConstants,
    MarketingAnalyticsTableQuery,
} from '~/queries/schema/schema-general'

export type MarketingTableColumnView = 'default' | 'clicks' | 'conversions'

export const MARKETING_TABLE_COLUMN_VIEWS: { value: MarketingTableColumnView; label: string }[] = [
    { value: 'default', label: 'Default' },
    { value: 'clicks', label: 'Click-through' },
    { value: 'conversions', label: 'Conversions' },
]

const PLATFORM_METRICS = new Set<string>([
    MarketingAnalyticsBaseColumns.Cost,
    MarketingAnalyticsBaseColumns.Clicks,
    MarketingAnalyticsBaseColumns.Impressions,
    MarketingAnalyticsBaseColumns.CPC,
    MarketingAnalyticsBaseColumns.CTR,
    MarketingAnalyticsBaseColumns.ReportedConversions,
    MarketingAnalyticsBaseColumns.ReportedConversionValue,
    MarketingAnalyticsBaseColumns.ReportedROAS,
    MarketingAnalyticsBaseColumns.CostPerReportedConversions,
])

const VIEW_METRICS: Record<MarketingTableColumnView, Set<string>> = {
    default: new Set([
        MarketingAnalyticsBaseColumns.Cost,
        MarketingAnalyticsBaseColumns.Clicks,
        MarketingAnalyticsBaseColumns.CTR,
        MarketingAnalyticsBaseColumns.ReportedConversions,
    ]),
    clicks: new Set([
        MarketingAnalyticsBaseColumns.Cost,
        MarketingAnalyticsBaseColumns.Impressions,
        MarketingAnalyticsBaseColumns.Clicks,
        MarketingAnalyticsBaseColumns.CTR,
        MarketingAnalyticsBaseColumns.CPC,
    ]),
    conversions: new Set([
        MarketingAnalyticsBaseColumns.Cost,
        MarketingAnalyticsBaseColumns.ReportedConversions,
        MarketingAnalyticsBaseColumns.CostPerReportedConversions,
        MarketingAnalyticsBaseColumns.ReportedConversionValue,
        MarketingAnalyticsBaseColumns.ReportedROAS,
    ]),
}

const DIMENSIONS = new Set<string>([
    MarketingAnalyticsBaseColumns.Id,
    MarketingAnalyticsBaseColumns.Campaign,
    MarketingAnalyticsBaseColumns.Source,
    MarketingAnalyticsBaseColumns.AdGroup,
    MarketingAnalyticsBaseColumns.AdGroupId,
    MarketingAnalyticsBaseColumns.Ad,
    MarketingAnalyticsBaseColumns.AdId,
    ...Object.values(MARKETING_ANALYTICS_DRILL_DOWN_CONFIG).map((config) => config.columnAlias),
])

export function marketingTableDimensionColumns(columns: string[]): string[] {
    return columns.filter((column) => DIMENSIONS.has(column))
}

function sameColumns(a: string[], b: string[]): boolean {
    return a.length === b.length && a.every((column) => b.includes(column))
}

/** Drops the pins when they equal the default for the current columns, so each drill-down level computes its own. */
export function withoutDefaultPins(query: DataTableNode): DataTableNode {
    const select = (query.source as MarketingAnalyticsTableQuery).select ?? []
    if (query.pinnedColumns && sameColumns(query.pinnedColumns, marketingTableDimensionColumns(select))) {
        return { ...query, pinnedColumns: undefined }
    }
    return query
}

/** Conversion goals and their cost per conversion, which PostHog calculates from events. */
export function isPostHogColumn(column: string): boolean {
    return !DIMENSIONS.has(column) && !PLATFORM_METRICS.has(column)
}

// A goal can itself be named "Cost per ...", so only a column whose goal is also in the table counts as a cost.
function isCostPerGoal(column: string, availableColumns: Set<string>): boolean {
    const prefix = `${MarketingAnalyticsConstants.CostPer} `
    return column.startsWith(prefix) && availableColumns.has(column.slice(prefix.length))
}

function inView(view: MarketingTableColumnView, column: string, availableColumns: Set<string>): boolean {
    if (DIMENSIONS.has(column)) {
        return true
    }
    if (isPostHogColumn(column)) {
        return view === 'conversions' || (view === 'default' && !isCostPerGoal(column, availableColumns))
    }
    return VIEW_METRICS[view].has(column)
}

/** The columns a view shows, in the order of `availableColumns` so breakdown columns stay first. */
export function columnsForView(view: MarketingTableColumnView, availableColumns: string[]): string[] {
    const available = new Set(availableColumns)
    return availableColumns.filter((column) => inView(view, column, available))
}

/** The view the current columns match, or null once someone has picked columns by hand. */
export function activeColumnView(
    select: string[] | undefined,
    availableColumns: string[]
): MarketingTableColumnView | null {
    const current = select ?? columnsForView('default', availableColumns)
    return (
        MARKETING_TABLE_COLUMN_VIEWS.find(({ value }) => sameColumns(columnsForView(value, availableColumns), current))
            ?.value ?? null
    )
}
