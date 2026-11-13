import type { ComponentProps } from 'react'

import type { Badge } from '@posthog/quill'

import type { DataQualitySuiteRunApi } from './generated/api.schemas'

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

export type SuiteRunDotVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success'

export function suiteRunDotVariant(
    suiteRun: Pick<DataQualitySuiteRunApi, 'status' | 'checks_failed' | 'checks_errored'>
): SuiteRunDotVariant {
    if (suiteRun.status === 'running') {
        return 'info'
    }
    if (suiteRun.status === 'empty') {
        return 'default'
    }
    if (suiteRun.checks_failed > 0) {
        return 'destructive'
    }
    if (suiteRun.checks_errored > 0 || suiteRun.status === 'failed') {
        return 'warning'
    }
    return 'success'
}
