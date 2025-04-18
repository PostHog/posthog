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

export type BillingSectionId =
    | 'overview'
    | 'usage'
    | 'usage2'
    | 'usage3'
    | 'usage4'
    | 'usage5'
    | 'licenses'
    | 'invoices'
