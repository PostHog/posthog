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

export type BillingSectionId = 'overview' | 'usage' | 'spend' | 'seats'

export type SeatStatus = 'active' | 'canceling' | 'pending' | 'pending_payment' | 'expired' | 'withdrawn'

export interface SeatData {
    id: string
    user_distinct_id: string
    product_key: string
    plan_key: string
    status: SeatStatus
    end_reason: string | null
    created_at: string | number
    active_until: string | number | null
    active_from: string | number | null
}

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

export type BillingSeriesForCsv = {
    id: number
    label: string
    data: number[]
}

export interface BuildBillingCsvOptions {
    decimals?: number
}
