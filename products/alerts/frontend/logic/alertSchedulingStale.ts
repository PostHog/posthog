import { deepEqual as equal } from 'fast-equals'

import { Dayjs, dayjs } from 'lib/dayjs'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import type { ScheduleRestriction } from '../types'

function calendarAnchor(localDate: Dayjs, hour: number, timezone: string): Dayjs {
    return dayjs.tz(`${localDate.format('YYYY-MM-DD')} ${hour}:00`, 'YYYY-MM-DD H:mm', timezone)
}

export function approximateNextAlertRun(
    interval: AlertCalculationInterval,
    timezone: string,
    now: Dayjs = dayjs()
): Dayjs {
    let localNow: Dayjs
    try {
        localNow = now.tz(timezone)
    } catch {
        timezone = 'UTC'
        localNow = now.utc()
    }

    switch (interval) {
        case AlertCalculationInterval.REAL_TIME:
            return localNow.add(2, 'minutes')
        case AlertCalculationInterval.EVERY_15_MINUTES:
            return localNow.add(15, 'minutes')
        case AlertCalculationInterval.HOURLY:
            return localNow.add(1, 'hour')
        case AlertCalculationInterval.DAILY:
            return calendarAnchor(localNow.add(1, 'day'), 1, timezone)
        case AlertCalculationInterval.WEEKLY: {
            const daysUntilMonday = localNow.day() === 0 ? 1 : 8 - localNow.day()
            return calendarAnchor(localNow.add(daysUntilMonday, 'days'), 3, timezone)
        }
        case AlertCalculationInterval.MONTHLY:
            return calendarAnchor(localNow.add(1, 'month').startOf('month'), 4, timezone)
    }
}

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
