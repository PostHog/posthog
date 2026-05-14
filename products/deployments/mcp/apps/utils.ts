export type DeploymentStatus = 'queued' | 'initializing' | 'building' | 'ready' | 'error' | 'cancelled'

export const STATUS_VARIANTS: Record<
    DeploymentStatus | string,
    'success' | 'destructive' | 'info' | 'warning' | 'default'
> = {
    ready: 'success',
    error: 'destructive',
    building: 'info',
    queued: 'default',
    initializing: 'default',
    cancelled: 'warning',
}

export const STATUS_LABELS: Record<DeploymentStatus | string, string> = {
    ready: 'Ready',
    error: 'Error',
    building: 'Building',
    queued: 'Queued',
    initializing: 'Initializing',
    cancelled: 'Cancelled',
}

export function formatDuration(seconds: number | null | undefined): string {
    if (seconds == null) {
        return '—'
    }
    if (seconds < 60) {
        return `${seconds}s`
    }
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return s === 0 ? `${m}m` : `${m}m ${s}s`
}
