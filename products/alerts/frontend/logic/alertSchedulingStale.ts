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
    scheduleStartTime: string | null | undefined = null,
    now: Dayjs = dayjs()
): { earliest: Dayjs; latest: Dayjs } {
    let localNow: Dayjs
    try {
        localNow = now.tz(timezone)
    } catch {
        timezone = 'UTC'
        localNow = now.utc()
    }

    const scheduleStartMinute = scheduleStartTime ? Number(scheduleStartTime.split(':')[1]) : undefined
    const nextRunFromScheduleStartMinute = (cadenceMinutes: number): Dayjs | null => {
        if (
            scheduleStartMinute === undefined ||
            !Number.isInteger(scheduleStartMinute) ||
            scheduleStartMinute < 0 ||
            scheduleStartMinute > 59
        ) {
            return null
        }

        let candidate = localNow.startOf('hour').minute(scheduleStartMinute).second(0).millisecond(0)
        while (!candidate.isAfter(localNow)) {
            candidate = candidate.add(cadenceMinutes, 'minutes')
        }
        return candidate
    }

    if (interval === AlertCalculationInterval.REAL_TIME) {
        const nextRun = localNow.add(2, 'minutes')
        return { earliest: nextRun, latest: nextRun }
    }
    if (interval === AlertCalculationInterval.EVERY_15_MINUTES || interval === AlertCalculationInterval.HOURLY) {
        const cadence = interval === AlertCalculationInterval.EVERY_15_MINUTES ? 15 : 60
        const customRun = nextRunFromScheduleStartMinute(cadence)
        if (customRun) {
            return { earliest: customRun, latest: customRun }
        }
        const anchor = localNow.startOf('minute').add(cadence - (localNow.minute() % cadence), 'minutes')
        return {
            earliest: anchor.add(cadence === 15 ? 1 : 2, 'minutes'),
            latest: anchor.add(cadence === 15 ? 3 : 13, 'minutes'),
        }
    }

    let anchor: Dayjs
    switch (interval) {
        case AlertCalculationInterval.DAILY:
            anchor = calendarAnchor(localNow.add(1, 'day'), 1, timezone)
            break
        case AlertCalculationInterval.WEEKLY: {
            const daysUntilMonday = localNow.day() === 0 ? 1 : 8 - localNow.day()
            anchor = calendarAnchor(localNow.add(daysUntilMonday, 'days'), 3, timezone)
            break
        }
        case AlertCalculationInterval.MONTHLY:
            anchor = calendarAnchor(localNow.add(1, 'month').startOf('month'), 4, timezone)
            break
    }
    return { earliest: anchor.add(2, 'minutes'), latest: anchor.add(59, 'minutes') }
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
    schedule_start_time?: string | null
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
    if (form.schedule_start_time !== saved.schedule_start_time) {
        return true
    }
    if (Boolean(form.config?.check_ongoing_interval) !== Boolean(saved.config?.check_ongoing_interval)) {
        return true
    }
    return false
}
