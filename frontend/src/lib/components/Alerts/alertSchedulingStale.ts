import equal from 'fast-deep-equal'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import type { ScheduleRestriction } from './types'

export function normalizeScheduleRestrictionForCompare(
    sr: ScheduleRestriction | null | undefined
): ScheduleRestriction | null {
    if (!sr?.blocked_windows?.length) {
        return null
    }
    return sr
}

/** Subset of alert + form used to detect whether shown `next_check_at` may be outdated. */
export type SchedulingSnapshot = {
    calculation_interval: AlertCalculationInterval
    schedule_restriction?: ScheduleRestriction | null
    skip_weekend?: boolean | null
    config?: { check_ongoing_interval?: boolean } | null
}

export function isNextPlannedEvaluationStale(
    creatingNewAlert: boolean,
    saved: SchedulingSnapshot | null | undefined,
    form: SchedulingSnapshot | null | undefined
): boolean {
    if (creatingNewAlert || !saved || !form) {
        return false
    }
    if (form.calculation_interval !== saved.calculation_interval) {
        return true
    }
    if (
        !equal(
            normalizeScheduleRestrictionForCompare(form.schedule_restriction),
            normalizeScheduleRestrictionForCompare(saved.schedule_restriction)
        )
    ) {
        return true
    }
    if (Boolean(form.skip_weekend) !== Boolean(saved.skip_weekend)) {
        return true
    }
    if (Boolean(form.config?.check_ongoing_interval) !== Boolean(saved.config?.check_ongoing_interval)) {
        return true
    }
    return false
}
