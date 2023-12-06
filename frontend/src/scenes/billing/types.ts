export enum BillingGaugeItemType {
    FreeTier = 'free_tier',
    CurrentUsage = 'current_usage',
    ProjectedUsage = 'projected_usage',
    BillingLimit = 'billing_limit',
}

export type BillingGaugeItem = {
    type: BillingGaugeItemType
    text: string | JSX.Element
    color: string
    value: number
    top: boolean
}
