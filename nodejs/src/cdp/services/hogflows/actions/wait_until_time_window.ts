import { DateTime } from 'luxon'

import { CyclotronPerson } from '~/cdp/types'
import { HogFlowAction } from '~/schema/hogflow'

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
        return {
            nextAction: findContinueAction(invocation),
            scheduledAt: nextTime ?? undefined,
        }
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
        return getNextValidDay(now, config.day)
    }

    const [startTime, endTime] = config.time
    const [startHours, startMinutes] = startTime.split(':').map(Number)
    const [endHours, endMinutes] = endTime.split(':').map(Number)

    // Try today first
    let nextTime = now.set({ hour: startHours, minute: startMinutes, second: 0, millisecond: 0 })
    const endTimeToday = now.set({ hour: endHours, minute: endMinutes, second: 0, millisecond: 0 })

    // If we're within the time window today, execute immediately
    if (now >= nextTime && now <= endTimeToday && isValidDay(now, config.day)) {
        return null
    }

    // If time has passed or day doesn't match, find next valid day
    if (nextTime <= now || !isValidDay(nextTime, config.day)) {
        nextTime = getNextValidDay(now, config.day).set({
            hour: startHours,
            minute: startMinutes,
            second: 0,
            millisecond: 0,
        })
    }

    return nextTime
}
