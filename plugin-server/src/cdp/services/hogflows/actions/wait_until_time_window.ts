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
        const isResumingFromWait = this.isResumingFromWaitUntilTimeWindow(invocation, action)

        if (isResumingFromWait) {
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

        const actionStartedAt = DateTime.fromMillis(startedAtTimestamp).toUTC()
        const waitUntilTime = getWaitUntilTimeForAction(action, actionStartedAt)

        // If waitUntilTime is null, it means we were already in the window when the action started,
        // so we should have executed immediately. Otherwise, check if we're past the scheduled time.
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
    return getWaitUntilTimeForAction(action, now)
}

function getWaitUntilTimeForAction(
    action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>,
    startTime: DateTime
): DateTime | null {
    const startTimeInZone = startTime.setZone(action.config.timezone || 'UTC')
    const config = action.config

    if (config.time === 'any') {
        return getNextValidDay(startTimeInZone, config.day)
    }

    const [startHours, startMinutes] = config.time[0].split(':').map(Number)
    const [endHours, endMinutes] = config.time[1].split(':').map(Number)

    // Try the time window on the start day
    let nextTime = startTimeInZone.set({ hour: startHours, minute: startMinutes, second: 0, millisecond: 0 })
    const endTimeOnStartDay = startTimeInZone.set({ hour: endHours, minute: endMinutes, second: 0, millisecond: 0 })

    // If we were within the time window when the action started, execute immediately
    if (
        startTimeInZone >= nextTime &&
        startTimeInZone <= endTimeOnStartDay &&
        isValidDay(startTimeInZone, config.day)
    ) {
        return null
    }

    // If time has passed or day doesn't match, find next valid day
    if (nextTime <= startTimeInZone || !isValidDay(nextTime, config.day)) {
        nextTime = getNextValidDay(startTimeInZone, config.day).set({
            hour: startHours,
            minute: startMinutes,
            second: 0,
            millisecond: 0,
        })
    }

    return nextTime
}
