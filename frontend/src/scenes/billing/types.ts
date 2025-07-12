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

export type BillingSectionId = 'overview' | 'usage' | 'spend'

export interface BillingFilters {
    usage_types?: string[]
    team_ids?: number[]
    breakdowns?: ('type' | 'team')[]
    interval?: 'day' | 'week' | 'month'
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
