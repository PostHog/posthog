import { Badge } from '@posthog/quill'

type BadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success'

const STATUS_STYLE: Record<string, { variant: BadgeVariant; label: string }> = {
    running: { variant: 'info', label: 'Running' },
    queued: { variant: 'warning', label: 'Queued' },
    finished: { variant: 'success', label: 'Finished' },
    failed: { variant: 'destructive', label: 'Failed' },
    disabled: { variant: 'default', label: 'Disabled' },
    active: { variant: 'success', label: 'Active' },
    // Readiness states of warehouse data
    not_configured: { variant: 'default', label: 'Not configured' },
    waiting: { variant: 'warning', label: 'Waiting' },
    backfilling: { variant: 'info', label: 'Backfilling' },
    up_to_date: { variant: 'success', label: 'Up to date' },
    needs_attention: { variant: 'destructive', label: 'Needs attention' },
    sync_paused: { variant: 'default', label: 'Sync paused' },
}

/** The one status pill of the console. Unknown states render as a muted pill with their own name. */
export function WarehouseStatusBadge({ status }: { status: string }): JSX.Element {
    const key = status.toLowerCase()
    const style = STATUS_STYLE[key] ?? {
        variant: 'default' as const,
        label: key.charAt(0).toUpperCase() + key.slice(1).replaceAll('_', ' '),
    }
    return <Badge variant={style.variant}>{style.label}</Badge>
}
