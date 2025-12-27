import { DateTime } from 'luxon'

import { HogFlowAction } from '~/schema/hogflow'

import { CyclotronJobInvocationHogFlow } from '../../../types'
import { actionIdForLogging, findContinueAction } from '../hogflow-utils'
import { ActionHandler, ActionHandlerOptions, ActionHandlerResult } from './action.interface'

type Action = Extract<HogFlowAction, { type: 'wait_until_time_window' }>

const DAY_NAMES = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'] as const

export class WaitUntilTimeWindowHandler implements ActionHandler {
    execute({
        invocation,
        action,
        result,
    }: ActionHandlerOptions<Extract<HogFlowAction, { type: 'wait_until_time_window' }>>): ActionHandlerResult {
        // Check if we're resuming from a wait_until_time_window (queueScheduledAt was cleared when queue consumed the job)
        const isResuming = !invocation.queueScheduledAt && this.isResumingFromWaitUntilTimeWindow(invocation, action)

        if (isResuming) {
            const nextAction = findContinueAction(invocation)
            result.logs.push({
                level: 'info',
                timestamp: DateTime.now(),
                message: `${actionIdForLogging(action)} Wait until time window completed, resuming workflow with latest workflow definition`,
            })
            return {
                nextAction,
            }
        }

        const nextTime = getWaitUntilTime(action)

        return {
            scheduledAt: nextTime ?? undefined,
        }
    }

    private isResumingFromWaitUntilTimeWindow(
        invocation: CyclotronJobInvocationHogFlow,
        action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>
    ): boolean {
        const startedAtTimestamp = invocation.state.currentAction?.startedAtTimestamp
        if (!startedAtTimestamp) {
            return false
        }

        // Recalculate when the wait until time should be
        const waitUntilTime = getWaitUntilTime(action)
        // If getWaitUntilTime returns null, it means we're within the time window and should execute immediately
        return waitUntilTime === null || DateTime.utc() >= waitUntilTime
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

export const getWaitUntilTime = (
    action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>
): DateTime | null => {
    const now = DateTime.utc().setZone(action.config.timezone || 'UTC')
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
