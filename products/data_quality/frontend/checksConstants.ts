import { Dayjs, dayjs } from 'lib/dayjs'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'

import { CheckTypeEnumApi } from './generated/api.schemas'
import type { DataQualityCheckApi } from './generated/api.schemas'

export const CHECK_TYPE_LABELS: Record<string, string> = {
    [CheckTypeEnumApi.NotNull]: 'Not null',
    [CheckTypeEnumApi.Unique]: 'Unique',
    [CheckTypeEnumApi.AcceptedValues]: 'Accepted values',
    [CheckTypeEnumApi.Relationships]: 'Relationship',
    [CheckTypeEnumApi.RowCount]: 'Row count',
    [CheckTypeEnumApi.Freshness]: 'Freshness',
    [CheckTypeEnumApi.CustomSql]: 'Custom SQL',
}

export const CHECK_STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    passed: 'success',
    failed: 'danger',
    errored: 'warning',
    skipped: 'muted',
}

export const SUITE_RUN_STATUS_TAG_TYPES: Record<string, LemonTagType> = {
    running: 'primary',
    completed: 'success',
    failed: 'danger',
    empty: 'muted',
}

export const HEALTH_TAG_TYPES: Record<string, LemonTagType> = {
    healthy: 'success',
    warn: 'warning',
    failing: 'danger',
    erroring: 'warning',
    unknown: 'muted',
}

export const HEALTH_LABELS: Record<string, string> = {
    healthy: 'Healthy',
    warn: 'Warning',
    failing: 'Failing',
    erroring: 'Erroring',
    unknown: 'Not run yet',
}

/** Matches the vocabulary the lineage graph uses for the same objects, without importing across products. */
export const SUBJECT_TYPE_TAGS: Record<string, { label: string; type: LemonTagType }> = {
    table: { label: 'Table', type: 'default' },
    view: { label: 'View', type: 'primary' },
}

export const SEVERITY_TAG_TYPES: Record<string, LemonTagType> = {
    error: 'danger',
    warn: 'warning',
}

const FAILING_STATUSES = ['failed', 'errored']

/**
 * How long a check has been broken, or null when it is not broken. The first question a red row
 * raises. Kept short because it sits beside the status tag, which already says it failed.
 */
export function failingForLabel(
    check: Pick<DataQualityCheckApi, 'last_status' | 'last_succeeded_at'>,
    now: Dayjs = dayjs()
): string | null {
    if (!FAILING_STATUSES.includes(check.last_status ?? '')) {
        return null
    }
    if (!check.last_succeeded_at) {
        return 'never passed'
    }
    return `for ${dayjs(check.last_succeeded_at).from(now, true)}`
}

export function checkTypeLabel(checkType: string): string {
    return CHECK_TYPE_LABELS[checkType] ?? checkType
}

/** The check's own name when it has one, otherwise a description of the assertion it makes. */
export function checkDisplayName(check: Pick<DataQualityCheckApi, 'name' | 'check_type' | 'column_name'>): string {
    if (check.name) {
        return check.name
    }
    const label = checkTypeLabel(check.check_type)
    return check.column_name ? `${label} on ${check.column_name}` : label
}
