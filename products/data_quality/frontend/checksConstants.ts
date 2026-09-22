import { Dayjs, dayjs } from 'lib/dayjs'
import { LemonTagType } from 'lib/lemon-ui/LemonTag'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { CheckTypeEnumApi } from './generated/api.schemas'
import type { DataQualityCheckApi, DataQualityCheckRunApi } from './generated/api.schemas'

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

const CHECK_STATUS_ATTENTION_ORDER: Record<string, number> = {
    failed: 0,
    errored: 1,
    skipped: 2,
    passed: 3,
}

const LAST_ATTENTION_RANK = Object.keys(CHECK_STATUS_ATTENTION_ORDER).length

export function byStatusAttention(
    a: Pick<DataQualityCheckRunApi, 'status'>,
    b: Pick<DataQualityCheckRunApi, 'status'>
): number {
    return (
        (CHECK_STATUS_ATTENTION_ORDER[a.status] ?? LAST_ATTENTION_RANK) -
        (CHECK_STATUS_ATTENTION_ORDER[b.status] ?? LAST_ATTENTION_RANK)
    )
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
    metric: { label: 'Metric', type: 'option' },
    posthog_table: { label: 'PostHog', type: 'highlight' },
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
    check: Pick<DataQualityCheckApi, 'last_status' | 'last_succeeded_at' | 'failing_since'>,
    now: Dayjs = dayjs()
): string | null {
    if (!FAILING_STATUSES.includes(check.last_status ?? '')) {
        return null
    }
    if (check.failing_since) {
        return `for ${dayjs(check.failing_since).from(now, true)}`
    }
    return check.last_succeeded_at ? null : 'never passed'
}

export function checkTypeLabel(checkType: string): string {
    return CHECK_TYPE_LABELS[checkType] ?? checkType
}

export function subjectTypeLabel(subjectType: string): string {
    return SUBJECT_TYPE_TAGS[subjectType]?.label ?? subjectType
}

interface NamedCheck {
    name?: string | null
    check_type: string
    column_name?: string | null
}

/** The check's own name when it has one, otherwise a description of the assertion it makes. */
export function checkDisplayName(check: NamedCheck): string {
    if (check.name) {
        return check.name
    }
    const label = checkTypeLabel(check.check_type)
    return check.column_name ? `${label} on ${check.column_name}` : label
}

export function checkRunDisplayName(
    run: Pick<DataQualityCheckRunApi, 'check_name' | 'check_type' | 'column_name'>
): string {
    return checkDisplayName({ name: run.check_name, check_type: run.check_type, column_name: run.column_name })
}

const SECONDS_PER_MINUTE = 60
const DURATION_UNITS = 2

const FAILING_ROW_NOUNS: Partial<Record<CheckTypeEnumApi, [string, string]>> = {
    [CheckTypeEnumApi.NotNull]: ['null row', 'null rows'],
    [CheckTypeEnumApi.Unique]: ['duplicate value', 'duplicate values'],
    [CheckTypeEnumApi.AcceptedValues]: ['row outside the set', 'rows outside the set'],
    [CheckTypeEnumApi.Relationships]: ['row with no match', 'rows with no match'],
    [CheckTypeEnumApi.CustomSql]: ['row returned', 'rows returned'],
}

export interface RunResultCell {
    label: string
    tooltip: string | null
}

export function runResultCell(
    run: Pick<DataQualityCheckRunApi, 'check_type' | 'observed_value' | 'check_config'>
): RunResultCell {
    if (run.observed_value === null) {
        return { label: '-', tooltip: null }
    }
    if (run.check_type === CheckTypeEnumApi.Freshness) {
        return freshnessCell(run.observed_value, run.check_config)
    }
    if (run.check_type === CheckTypeEnumApi.RowCount) {
        return rowCountCell(run.observed_value, run.check_config)
    }
    const nouns = FAILING_ROW_NOUNS[run.check_type]
    if (!nouns) {
        return { label: humanFriendlyNumber(run.observed_value), tooltip: null }
    }
    return { label: pluralize(run.observed_value, nouns[0], nouns[1]), tooltip: null }
}

function freshnessCell(stalenessSeconds: number, config: DataQualityCheckRunApi['check_config']): RunResultCell {
    const maxAgeMinutes = config?.max_age_minutes
    const limit =
        typeof maxAgeMinutes === 'number'
            ? ` The limit is ${humanFriendlyDuration(maxAgeMinutes * SECONDS_PER_MINUTE, { maxUnits: DURATION_UNITS })}.`
            : ''
    const direction = stalenessSeconds < 0 ? 'in the future' : 'old'
    const magnitude = Math.abs(stalenessSeconds)
    return {
        label: `${humanFriendlyDuration(magnitude, { maxUnits: DURATION_UNITS })} ${direction}`,
        tooltip: `Newest row is ${humanFriendlyNumber(magnitude)} seconds ${direction}.${limit}`,
    }
}

function rowCountCell(rowCount: number, config: DataQualityCheckRunApi['check_config']): RunResultCell {
    const label = pluralize(rowCount, 'row')
    const limit = rowCountLimit(config?.min, config?.max)
    return { label, tooltip: limit ? `${label}. The limit is ${limit}.` : null }
}

function rowCountLimit(min: unknown, max: unknown): string | null {
    const hasMin = typeof min === 'number'
    const hasMax = typeof max === 'number'
    if (hasMin && hasMax) {
        return `between ${humanFriendlyNumber(min)} and ${pluralize(max, 'row')}`
    }
    if (hasMin) {
        return `at least ${pluralize(min, 'row')}`
    }
    if (hasMax) {
        return `at most ${pluralize(max, 'row')}`
    }
    return null
}
