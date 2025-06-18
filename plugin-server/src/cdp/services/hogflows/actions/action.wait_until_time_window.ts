import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionResult } from './types'

type Action = Extract<HogFlowAction, { type: 'wait_until_time_window' }>

const DAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const

export class HogFlowActionRunnerWaitUntilTimeWindow {
    run(action: Action): HogFlowActionResult {
        const now = DateTime.utc().setZone(action.config.timezone)
        const nextTime = this.getNextValidTime(now, action.config)

        return {
            done: true,
            scheduledAt: nextTime ?? undefined,
        }
    }

    private getNextValidTime(now: DateTime, config: Action['config']): DateTime | null {
        // If time is 'any', just find next valid day
        if (config.time === 'any') {
            return this.getNextValidDay(now, config.date)
        }

        const [startTime, endTime] = config.time
        const [startHours, startMinutes] = startTime.split(':').map(Number)
        const [endHours, endMinutes] = endTime.split(':').map(Number)

        // Try today first
        let nextTime = now.set({ hour: startHours, minute: startMinutes, second: 0, millisecond: 0 })
        const endTimeToday = now.set({ hour: endHours, minute: endMinutes, second: 0, millisecond: 0 })

        // If we're within the time window today, execute immediately
        if (now >= nextTime && now <= endTimeToday && this.isValidDay(now, config.date)) {
            return null
        }

        // If time has passed or day doesn't match, find next valid day
        if (nextTime <= now || !this.isValidDay(nextTime, config.date)) {
            nextTime = this.getNextValidDay(now, config.date).set({
                hour: startHours,
                minute: startMinutes,
                second: 0,
                millisecond: 0,
            })
        }

        return nextTime
    }

    private isValidDay(date: DateTime, dateConfig: Action['config']['date']): boolean {
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

    private getNextValidDay(now: DateTime, dateConfig: Action['config']['date']): DateTime {
        let nextDay = now.plus({ days: 1 }).startOf('day')

        while (!this.isValidDay(nextDay, dateConfig)) {
            nextDay = nextDay.plus({ days: 1 })
        }

        return nextDay
    }
}
