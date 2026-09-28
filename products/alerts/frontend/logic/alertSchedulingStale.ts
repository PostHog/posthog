import { deepEqual as equal } from 'fast-equals'

import { Dayjs, dayjs } from 'lib/dayjs'

import { AlertCalculationInterval } from '~/queries/schema/schema-general'

import type { ScheduleRestriction } from '../types'

function calendarTime(localDate: Dayjs, hour: number, minute: number, timezone: string): Dayjs {
    return dayjs.tz(
        `${localDate.format('YYYY-MM-DD')} ${hour}:${String(minute).padStart(2, '0')}`,
        'YYYY-MM-DD H:mm',
        timezone
    )
}

function parseScheduleStartTime(scheduleStartTime: string | null | undefined): { hour: number; minute: number } | null {
    const [hour, minute] = (scheduleStartTime ?? '').split(':').map(Number)
    if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
        return null
    }
    return { hour, minute }
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

    const scheduleStart = parseScheduleStartTime(scheduleStartTime)
    const nextRunFromScheduleStartMinute = (cadenceMinutes: number): Dayjs | null => {
        if (!scheduleStart) {
            return null
        }

        let candidate = localNow.startOf('hour').minute(scheduleStart.minute).second(0).millisecond(0)
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

    if (scheduleStart) {
        // An explicit start time runs at exactly that local time: today, this Monday, or the 1st of this
        // month, moved on by whole days, weeks, or months until it is in the future.
        let firstDate: Dayjs
        let unit: 'day' | 'week' | 'month'
        switch (interval) {
            case AlertCalculationInterval.DAILY:
                firstDate = localNow
                unit = 'day'
                break
            case AlertCalculationInterval.WEEKLY:
                firstDate = localNow.add((8 - localNow.day()) % 7, 'days')
                unit = 'week'
                break
            case AlertCalculationInterval.MONTHLY:
                firstDate = localNow.startOf('month')
                unit = 'month'
                break
        }
        let steps = 0
        let run = calendarTime(firstDate, scheduleStart.hour, scheduleStart.minute, timezone)
        while (!run.isAfter(localNow)) {
            steps += 1
            run = calendarTime(firstDate.add(steps, unit), scheduleStart.hour, scheduleStart.minute, timezone)
        }
        return { earliest: run, latest: run }
    }

    let anchor: Dayjs
    switch (interval) {
        case AlertCalculationInterval.DAILY:
            anchor = calendarTime(localNow.add(1, 'day'), 1, 0, timezone)
            break
        case AlertCalculationInterval.WEEKLY: {
            const daysUntilMonday = localNow.day() === 0 ? 1 : 8 - localNow.day()
            anchor = calendarTime(localNow.add(daysUntilMonday, 'days'), 3, 0, timezone)
            break
        }
        case AlertCalculationInterval.MONTHLY:
            anchor = calendarTime(localNow.add(1, 'month').startOf('month'), 4, 0, timezone)
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
