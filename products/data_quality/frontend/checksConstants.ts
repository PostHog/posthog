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

export const SEVERITY_TAG_TYPES: Record<string, LemonTagType> = {
    error: 'danger',
    warn: 'warning',
}

export function checkTypeLabel(checkType: string): string {
    return CHECK_TYPE_LABELS[checkType] ?? checkType
}

/** The check's own name when it has one, otherwise a description of the assertion it makes. */
export function checkDisplayName(check: DataQualityCheckApi): string {
    if (check.name) {
        return check.name
    }
    const label = checkTypeLabel(check.check_type)
    return check.column_name ? `${label} on ${check.column_name}` : label
}
