import { DateTime } from 'luxon'

import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronPerson } from '~/cdp/types'

import { findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type Action = Extract<HogFlowAction, { type: 'wait_until_time_window' }>

const DAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const
const GEOIP_TIMEZONE_PROPERTY = '$geoip_time_zone'

export class WaitUntilTimeWindowHandler implements ActionHandler {
    execute({
        invocation,
        action,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'wait_until_time_window' }>>): ActionHandlerResult {
        const nextTime = getWaitUntilTime(action, invocation.person)

        // Same as the delay handler: while still waiting for the window, park WITHOUT advancing
        // currentAction, so the job doesn't look like it has reached the next step (which the
        // subscription matcher could wake early). Advance only once the window has opened.
        if (nextTime) {
            return { scheduledAt: nextTime }
        }

        return { nextAction: findContinueAction(invocation) }
    }
}

function isValidDay(date: DateTime, dateConfig: Action['config']['day']): boolean {
    if (dateConfig === 'any') {
        return true
    }

    const day = date.weekday // 1 = Monday, 7 = Sunday
    const currentDay = DAY_NAMES[day - 1]

    if (dateConfig === 'weekday') {
        return day >= 1 && day <= 5
    }
    if (dateConfig === 'weekend') {
        return day === 6 || day === 7
    }
    if (Array.isArray(dateConfig)) {
        return dateConfig.includes(currentDay)
    }
    return false
}

function getNextValidDay(now: DateTime, dateConfig: Action['config']['day']): DateTime {
    let nextDay = now.plus({ days: 1 }).startOf('day')

    while (!isValidDay(nextDay, dateConfig)) {
        nextDay = nextDay.plus({ days: 1 })
    }

    return nextDay
}

function isValidTimezone(timezone: string): boolean {
    // Luxon returns an invalid DateTime if the timezone is not recognized
    return DateTime.utc().setZone(timezone).isValid
}

export function resolveTimezone(config: Action['config'], person?: CyclotronPerson): string {
    const fallback = config.fallback_timezone || config.timezone || 'UTC'

    if (config.use_person_timezone) {
        if (person?.properties) {
            const personTimezone = person.properties[GEOIP_TIMEZONE_PROPERTY]
            if (personTimezone && typeof personTimezone === 'string' && isValidTimezone(personTimezone)) {
                return personTimezone
            }
        }
        // Fall back if person doesn't exist, doesn't have a timezone, or timezone is invalid
        return fallback
    }
    // Use the configured timezone or default to UTC
    return config.timezone || 'UTC'
}

export const getWaitUntilTime = (
    action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>,
    person?: CyclotronPerson
): DateTime | null => {
    const timezone = resolveTimezone(action.config, person)
    const now = DateTime.utc().setZone(timezone)
    const config = action.config

    if (config.time === 'any') {
        // Any time on a valid day: if today is valid the window is already open, so return null to
        // advance now. Returning null is the only signal to advance — the handler re-parks otherwise.
        return isValidDay(now, config.day) ? null : getNextValidDay(now, config.day)
    }

    const [startTime, endTime] = config.time
    const [startHours, startMinutes] = startTime.split(':').map(Number)
    const [endHours, endMinutes] = endTime.split(':').map(Number)

    const startToday = now.set({ hour: startHours, minute: startMinutes, second: 0, millisecond: 0 })
    const endToday = now.set({ hour: endHours, minute: endMinutes, second: 0, millisecond: 0 })

    // A window whose end is not strictly after its start wraps past midnight (e.g. 23:00 -> 01:00).
    // It is open in two pieces: the evening piece [start, midnight) opened today, and the
    // early-morning piece [midnight, end] opened the previous day - so day validity for the morning
    // piece is checked against yesterday, the day the window actually started.
    const wrapsMidnight = endToday <= startToday

    const isOpen = wrapsMidnight
        ? (now >= startToday && isValidDay(now, config.day)) ||
          (now <= endToday && isValidDay(now.minus({ days: 1 }), config.day))
        : now >= startToday && now <= endToday && isValidDay(now, config.day)

    if (isOpen) {
        return null
    }

    // Not open: park at the next start of the window on a valid day.
    let nextStart = startToday
    if (nextStart <= now || !isValidDay(nextStart, config.day)) {
        nextStart = getNextValidDay(now, config.day).set({
            hour: startHours,
            minute: startMinutes,
            second: 0,
            millisecond: 0,
        })
    }

    return nextStart
}
