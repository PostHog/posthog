export enum BillingGaugeItemKind {
    FreeTier = 'free_tier',
    CurrentUsage = 'current_usage',
    ProjectedUsage = 'projected_usage',
    BillingLimit = 'billing_limit',
}

export type BillingGaugeItemType = {
    type: BillingGaugeItemKind
    text: string | JSX.Element
    prefix?: string
    value: number
}

export type BillingSectionId = 'overview' | 'usage' | 'spend' | 'alerts'

export interface BillingFilters {
    usage_types?: string[]
    team_ids?: number[]
    breakdowns?: ('type' | 'team')[]
    interval?: 'day' | 'week' | 'month'
    /**
     * With a project breakdown, show only this many highest-usage projects and fold the rest
     * into a single "all other projects" series. Only sent when breaking down by project.
     * `null` means show every project, which organizations with many projects cannot chart.
     */
    top_projects?: number | null
}

export type BillingUsageInteractionProps = {
    action: 'filters_changed' | 'date_changed' | 'breakdown_toggled' | 'series_toggled' | 'filters_cleared'
    filters: BillingFilters
    date_from: string | null
    date_to: string | null
    exclude_empty: boolean
    usage_types_count: number
    usage_types_total: number
    teams_count: number
    teams_total: number
    has_team_breakdown: boolean
    interval: BillingFilters['interval']
}

/** How the usage and spend breakdowns are drawn.
 *
 * A line shows each series' own shape over time. A stacked bar shows what the total is made of,
 * which is the question a spend breakdown is usually asked. Stacking only means something when
 * every series shares a unit, so the logics gate it - see canStackSeries.
 */
export type BillingChartType = 'line' | 'bar'
