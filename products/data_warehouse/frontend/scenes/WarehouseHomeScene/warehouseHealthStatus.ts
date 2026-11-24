export type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success'

const STATUS_BADGES: Record<string, { label: string; variant: BadgeVariant }> = {
    failed: { label: 'Failed', variant: 'destructive' },
    billing_limit: { label: 'Billing limit', variant: 'warning' },
    degraded: { label: 'Degraded', variant: 'warning' },
    disabled: { label: 'Disabled', variant: 'default' },
}

export function statusBadge(status: string): { label: string; variant: BadgeVariant } {
    return STATUS_BADGES[status] ?? { label: status, variant: 'default' }
}
