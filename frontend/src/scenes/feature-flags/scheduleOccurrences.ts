import { Dayjs, dayjs } from 'lib/dayjs'

import {
    FeatureFlagGroupType,
    FeatureFlagType,
    RecurrenceInterval,
    ScheduledChangeOperationType,
    ScheduledChangeRequestState,
    ScheduledChangeType,
} from '~/types'

/** Flag state as projected after a scheduled change occurrence has applied. */
export interface ScheduleProjectedState {
    active: boolean
    /** Max rollout percentage across release condition sets. Null when no condition sets exist. */
    rolloutPercentage: number | null
    /** Null for flags with no variants. */
    variantCount: number | null
}

export interface ScheduleOccurrence {
    /** ISO timestamp of when this occurrence fires. */
    timestamp: string
    operation: ScheduledChangeOperationType
    schedule: ScheduledChangeType
    projected: ScheduleProjectedState
    /** The occurrence will be skipped at fire time unless its approval request is approved first. */
    needsApproval: boolean
}

export const OCCURRENCE_CAP = 10
export const OCCURRENCE_HORIZON_DAYS = 90

const INTERVAL_UNIT: Record<RecurrenceInterval, 'day' | 'week' | 'month' | 'year'> = {
    [RecurrenceInterval.Daily]: 'day',
    [RecurrenceInterval.Weekly]: 'week',
    [RecurrenceInterval.Monthly]: 'month',
    [RecurrenceInterval.Yearly]: 'year',
}

/** Null/undefined rollout means the condition set matches 100% of its targets. */
export function maxRolloutPercentage(groups: FeatureFlagGroupType[] | undefined): number | null {
    if (!groups?.length) {
        return null
    }
    return Math.max(...groups.map((group) => group.rollout_percentage ?? 100))
}

function isPaused(sc: ScheduledChangeType): boolean {
    return !sc.is_recurring && (!!sc.recurrence_interval || !!sc.cron_expression)
}

// One-time changes whose approval request was rejected or expired will never apply.
// Recurring schedules stay: each occurrence is re-gated with a fresh request.
function isDeniedApproval(sc: ScheduledChangeType): boolean {
    return (
        !sc.is_recurring &&
        !sc.recurrence_interval &&
        !sc.cron_expression &&
        (sc.change_request?.state === ScheduledChangeRequestState.Rejected ||
            sc.change_request?.state === ScheduledChangeRequestState.Expired)
    )
}

/**
 * Expands active scheduled changes into the chronological list of upcoming occurrences, each with
 * the flag state projected after it applies (starting from the flag's current state).
 *
 * Every schedule contributes its `scheduled_at` occurrence. Cron schedules contribute only that one:
 * the backend keeps `scheduled_at` pointed at the next cron run, and cron expansion is not
 * replicated client-side. Fixed-interval recurring schedules expand further with date arithmetic,
 * bounded by their end date, the horizon, and the overall cap.
 */
export function expandScheduleOccurrences(
    schedules: ScheduledChangeType[],
    flag: Pick<FeatureFlagType, 'active' | 'filters'>,
    now: Dayjs
): ScheduleOccurrence[] {
    const horizon = now.add(OCCURRENCE_HORIZON_DAYS, 'day')
    const raw: { at: Dayjs; schedule: ScheduledChangeType }[] = []

    for (const schedule of schedules) {
        if (schedule.executed_at || isPaused(schedule) || isDeniedApproval(schedule)) {
            continue
        }
        const first = dayjs(schedule.scheduled_at)
        if (!first.isValid()) {
            continue
        }
        raw.push({ at: first, schedule })

        if (schedule.is_recurring && schedule.recurrence_interval && !schedule.cron_expression) {
            const unit = INTERVAL_UNIT[schedule.recurrence_interval]
            const end = schedule.end_date ? dayjs(schedule.end_date) : null
            // Derive each occurrence from the previous one, as the backend does when it advances
            // scheduled_at (process_scheduled_changes.compute_next_run). A month-end start then stays
            // clamped (Jan 31 -> Feb 28 -> Mar 28); adding from the origin each step would restore the
            // 31st and paint flip dates the flag never fires on.
            let next = first
            for (let step = 1; step < OCCURRENCE_CAP; step++) {
                next = next.add(1, unit)
                if (next.isAfter(horizon) || (end && next.isAfter(end))) {
                    break
                }
                raw.push({ at: next, schedule })
            }
        }
    }

    raw.sort((a, b) => a.at.valueOf() - b.at.valueOf() || a.schedule.id - b.schedule.id)

    let active = flag.active
    let rolloutPercentage = maxRolloutPercentage(flag.filters.groups)
    let variantCount = flag.filters.multivariate?.variants.length ?? null

    return raw.slice(0, OCCURRENCE_CAP).map(({ at, schedule }) => {
        const { payload } = schedule
        if (payload.operation === ScheduledChangeOperationType.UpdateStatus) {
            active = payload.value
        } else if (payload.operation === ScheduledChangeOperationType.AddReleaseCondition) {
            const added = maxRolloutPercentage(payload.value.groups)
            if (added !== null) {
                rolloutPercentage = rolloutPercentage === null ? added : Math.max(rolloutPercentage, added)
            }
        } else if (payload.operation === ScheduledChangeOperationType.UpdateVariants) {
            variantCount = payload.value.variants.length
        }
        return {
            timestamp: at.toISOString(),
            operation: payload.operation,
            schedule,
            projected: { active, rolloutPercentage, variantCount },
            needsApproval: schedule.change_request?.state === ScheduledChangeRequestState.Pending,
        }
    })
}
