import type { ComponentProps } from 'react'

import type { Badge } from '@posthog/quill'

export type CheckBadgeVariant = NonNullable<ComponentProps<typeof Badge>['variant']>

export const CHECK_STATUS_BADGE_VARIANTS: Record<string, CheckBadgeVariant> = {
    passed: 'success',
    failed: 'destructive',
    errored: 'warning',
    skipped: 'default',
}

export const SUITE_RUN_STATUS_BADGE_VARIANTS: Record<string, CheckBadgeVariant> = {
    running: 'info',
    completed: 'success',
    failed: 'destructive',
    empty: 'default',
}

export const HEALTH_BADGE_VARIANTS: Record<string, CheckBadgeVariant> = {
    healthy: 'success',
    warn: 'warning',
    failing: 'destructive',
    erroring: 'warning',
    unknown: 'default',
}

export const SEVERITY_BADGE_VARIANTS: Record<string, CheckBadgeVariant> = {
    error: 'destructive',
    warn: 'warning',
}
