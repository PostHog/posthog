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
    /** Max rollout of the condition this occurrence adds; null for other operations. */
    addedRolloutPercentage: number | null
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

/** Matches MAX_CATCHUP_ITERATIONS in posthog/tasks/process_scheduled_changes.py. */
const CATCHUP_CAP = 1000

/**
 * Advances a stalled recurring date to its first fire after `now`, as the sweep's catch-up loop
 * does. The sweep skips the missed fires instead of replaying them, so this projects one date.
 */
function catchUpToFuture(from: Dayjs, unit: 'day' | 'week' | 'month' | 'year', now: Dayjs): Dayjs {
    // Step from the previous date rather than add N intervals to the origin, because month-end
    // clamping is path dependent: a monthly schedule from Oct 31 gives Nov 30, then Dec 30.
    let next = from
    for (let step = 0; step < CATCHUP_CAP && !next.isAfter(now); step++) {
        next = next.add(1, unit)
    }
    // The sweep gives up the same way at its own cap and computes the next run from now.
    return next.isAfter(now) ? next : now.add(1, unit)
}

/** Null/undefined rollout means the condition set matches 100% of its targets. */
export function maxRolloutPercentage(groups: FeatureFlagGroupType[] | undefined): number | null {
    if (!groups?.length) {
        return null
    }
    return Math.max(...groups.map((group) => group.rollout_percentage ?? 100))
}

/** A paused recurring schedule keeps its recurrence config but has is_recurring=false. */
export function isSchedulePaused(sc: ScheduledChangeType): boolean {
    return !sc.is_recurring && (!!sc.recurrence_interval || !!sc.cron_expression)
}

// A bound approval request that was rejected or expired means its current occurrence will not
// apply: apply_gated_scheduled_change skips it. A one-time change is then dropped entirely; a
// recurring one loses only this occurrence — the backend advances scheduled_at and re-gates the next.
export function hasDeniedApprovalRequest(sc: ScheduledChangeType): boolean {
    return (
        sc.change_request?.state === ScheduledChangeRequestState.Rejected ||
        sc.change_request?.state === ScheduledChangeRequestState.Expired
    )
}

/**
 * Expands active scheduled changes into the chronological list of upcoming occurrences, each with
 * the flag state projected after it applies (starting from the flag's current state).
 *
 * Every schedule contributes its `scheduled_at` occurrence. Cron schedules contribute only that one:
 * the backend keeps `scheduled_at` pointed at the next cron run, and further runs are deliberately
 * not expanded here (lib/cron could compute them; one next-run point is enough for this panel).
 * Fixed-interval recurring schedules expand further with date arithmetic, bounded by their end
 * date, the horizon, and the overall cap.
 */
export function expandScheduleOccurrences(
    schedules: ScheduledChangeType[],
    flag: Pick<FeatureFlagType, 'active' | 'filters'>,
    now: Dayjs
): ScheduleOccurrence[] {
    const horizon = now.add(OCCURRENCE_HORIZON_DAYS, 'day')
    const raw: { at: Dayjs; schedule: ScheduledChangeType; isFirst: boolean }[] = []

    for (const schedule of schedules) {
        if (schedule.executed_at || isSchedulePaused(schedule)) {
            continue
        }
        // Parse in UTC so recurrence arithmetic below adds fixed 24h days/weeks, matching the
        // backend's relativedelta on the stored UTC instant. Browser-local .add() would preserve
        // wall-clock across a DST transition and drift the projected fire time by an hour.
        const parsed = dayjs.utc(schedule.scheduled_at)
        if (!parsed.isValid()) {
            continue
        }
        const end = schedule.end_date ? dayjs.utc(schedule.end_date) : null
        // The sweep closes out a recurring window whose end_date has passed, and it fires nothing
        // (process_scheduled_changes stamps executed_at when end_date <= now). Such a row can still
        // hold a future scheduled_at, because the sweep advances that date without reading end_date
        // and closes the row only once the date arrives.
        if (end && !end.isAfter(now) && (schedule.recurrence_interval || schedule.cron_expression)) {
            continue
        }
        // Only a fixed-interval recurrence expands here. A cron schedule contributes its stored
        // next run alone, because the client does not evaluate cron expressions.
        const unit =
            schedule.is_recurring && schedule.recurrence_interval && !schedule.cron_expression
                ? INTERVAL_UNIT[schedule.recurrence_interval]
                : null

        let first = parsed
        // isFirst distinguishes the occurrence the schedule's current change request covers from
        // the later ones the backend will re-gate. See needsApproval below.
        let isFirst = true
        if (!first.isAfter(now)) {
            // A stalled schedule keeps a past scheduled_at with executed_at still null: the sweep
            // defers on ApprovalRequired, and a recoverable failure retries in place. Projecting
            // that instant as upcoming clamps it to the axis origin and labels it "now".
            if (!unit) {
                continue
            }
            first = catchUpToFuture(first, unit, now)
            // The bound request covered the fire that never happened, so the sweep re-gates this
            // one and it must not read as certain.
            isFirst = false
        }
        if (end && first.isAfter(end)) {
            continue
        }
        // Skip a denied change's current occurrence; the backend re-gates the next, which the
        // recurrence expansion below still projects. A denied one-time schedule then ends up with
        // no occurrence at all, and so does a denied recurring cron schedule, because its next run
        // is not computed client-side.
        if (!(isFirst && hasDeniedApprovalRequest(schedule))) {
            raw.push({ at: first, schedule, isFirst })
        }

        if (unit) {
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
                raw.push({ at: next, schedule, isFirst: false })
            }
        }
    }

    raw.sort((a, b) => a.at.valueOf() - b.at.valueOf() || a.schedule.id - b.schedule.id)

    let active = flag.active
    let rolloutPercentage = maxRolloutPercentage(flag.filters.groups)
    let variantCount = flag.filters.multivariate?.variants.length ?? null

    return raw.slice(0, OCCURRENCE_CAP).map(({ at, schedule, isFirst }) => {
        const { payload } = schedule
        let addedRolloutPercentage: number | null = null
        if (payload.operation === ScheduledChangeOperationType.UpdateStatus) {
            active = payload.value
        } else if (payload.operation === ScheduledChangeOperationType.AddReleaseCondition) {
            addedRolloutPercentage = maxRolloutPercentage(payload.value.groups)
            if (addedRolloutPercentage !== null) {
                rolloutPercentage =
                    rolloutPercentage === null
                        ? addedRolloutPercentage
                        : Math.max(rolloutPercentage, addedRolloutPercentage)
            }
        } else if (payload.operation === ScheduledChangeOperationType.UpdateVariants) {
            variantCount = payload.value.variants.length
        }
        return {
            timestamp: at.toISOString(),
            operation: payload.operation,
            schedule,
            projected: { active, rolloutPercentage, variantCount },
            addedRolloutPercentage,
            // A bound change request covers one occurrence only. The first occurrence needs approval
            // when its own request is still pending. Every later occurrence of a gated schedule
            // needs one too: regate_recurring_scheduled_change binds a fresh pending request after
            // each fire, and apply_gated_scheduled_change skips an occurrence whose request is still
            // pending when the fire window closes.
            needsApproval: isFirst
                ? schedule.change_request?.state === ScheduledChangeRequestState.Pending
                : !!schedule.change_request,
        }
    })
}
