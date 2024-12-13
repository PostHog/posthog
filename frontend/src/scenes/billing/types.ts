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
    top: boolean
}
