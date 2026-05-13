import type { LemonTagType } from '@posthog/lemon-ui'

export const STATUS_COLOR: Record<string, LemonTagType> = {
    proposed: 'default',
    approved: 'primary',
    official: 'success',
    drift: 'warning',
}

export const STATUS_LABEL: Record<string, string> = {
    proposed: 'AI-proposed',
    approved: 'Approved',
    official: 'Official',
    drift: 'Drift detected',
}
