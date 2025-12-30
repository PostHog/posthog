import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlowAction } from '~/schema/hogflow'

import { CyclotronJobInvocationHogFlow } from '../../../types'
import { findActionByType } from '../hogflow-utils'
import { WaitUntilTimeWindowHandler, getWaitUntilTime } from './wait_until_time_window'

describe('HogFlowActionRunnerWaitUntilTimeWindow', () => {
    let action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T12:00:00.000Z')) // Wednesday at noon UTC

        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    wait_until_time_window: {
                        type: 'wait_until_time_window',
                        config: {
                            timezone: 'UTC',
                            day: 'any',
                            time: ['14:00', '16:00'],
                        },
                    },
                },
                edges: [],
            })
            .build()
        action = findActionByType(hogFlow, 'wait_until_time_window')!
    })

    describe('time window scheduling', () => {
        it('should schedule for today if time window is in the future', () => {
            const result = getWaitUntilTime(action)
            expect(result).toEqual(DateTime.utc().set({ hour: 14, minute: 0, second: 0, millisecond: 0 }))
        })

        it('should schedule immediately if current time is within window', () => {
            jest.setSystemTime(new Date('2025-01-01T15:00:00.000Z')) // Middle of window
            const result = getWaitUntilTime(action)
            expect(result).toEqual(null)
        })

        it('should schedule for tomorrow if time window has passed', () => {
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // After time window
            const result = getWaitUntilTime(action)
            expect(result).toEqual(
                DateTime.utc().plus({ days: 1 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 })
            )
        })

        it('should handle "any" time', () => {
            action.config.time = 'any'
            const result = getWaitUntilTime(action)
            expect(result).toEqual(DateTime.utc().plus({ days: 1 }).startOf('day'))
        })

        it('should handle time window spanning midnight', () => {
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-01T22:00:00.000Z')) // Before window
            const result = getWaitUntilTime(action)
            expect(result).toEqual(DateTime.utc().set({ hour: 23, minute: 0, second: 0, millisecond: 0 }))
        })

        it('should handle time window with minutes', () => {
            action.config.time = ['14:30', '15:45']
            const result = getWaitUntilTime(action)
            expect(result).toEqual(DateTime.utc().set({ hour: 14, minute: 30, second: 0, millisecond: 0 }))
        })

        it('should handle time window with minutes when current time is within window', () => {
            action.config.time = ['14:30', '15:45']
            jest.setSystemTime(new Date('2025-01-01T15:00:00.000Z')) // Middle of window
            const result = getWaitUntilTime(action)
            expect(result).toEqual(null)
        })
    })

    describe('day restrictions', () => {
        it('should handle weekday restriction', () => {
            action.config.day = 'weekday'
            jest.setSystemTime(new Date('2025-01-04T17:00:00.000Z')) // Saturday
            const result = getWaitUntilTime(action)
            expect(result).toEqual(
                DateTime.utc().plus({ days: 2 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 })
            )
        })

        it('should handle weekend restriction', () => {
            action.config.day = 'weekend'
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = getWaitUntilTime(action)
            expect(result).toEqual(
                DateTime.utc().plus({ days: 3 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 })
            )
        })

        it('should handle specific days', () => {
            action.config.day = ['monday', 'wednesday', 'friday']
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = getWaitUntilTime(action)
            expect(result).toEqual(
                DateTime.utc().plus({ days: 2 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 })
            )
        })

        it('should handle single specific day', () => {
            action.config.day = ['monday']
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = getWaitUntilTime(action)
            expect(result).toEqual(
                DateTime.utc().plus({ days: 5 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 })
            )
        })

        it('should handle consecutive days', () => {
            action.config.day = ['monday', 'tuesday', 'wednesday']
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = getWaitUntilTime(action)
            expect(result).toEqual(
                DateTime.utc().plus({ days: 5 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 })
            )
        })
    })

    describe('timezone handling', () => {
        it('should respect timezone setting', () => {
            action.config.timezone = 'America/New_York'
            const result = getWaitUntilTime(action)
            // Compare to UTC for easier understanding
            expect(DateTime.utc().setZone('America/New_York').toISO()).toMatchInlineSnapshot(
                `"2025-01-01T07:00:00.000-05:00"`
            )
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000-05:00"`)
        })

        it('should handle timezone with DST', () => {
            action.config.timezone = 'America/New_York'
            jest.setSystemTime(new Date('2025-07-01T12:00:00.000Z')) // Summer time
            const result = getWaitUntilTime(action)
            // Compare to UTC for easier understanding
            expect(DateTime.utc().setZone('America/New_York').toISO()).toMatchInlineSnapshot(
                `"2025-07-01T08:00:00.000-04:00"`
            )
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-07-01T14:00:00.000-04:00"`)
        })

        it('should handle timezone with negative offset', () => {
            action.config.timezone = 'Asia/Tokyo'

            const result = getWaitUntilTime(action)
            // Compare to UTC for easier understanding
            expect(DateTime.utc().setZone('Asia/Tokyo').toISO()).toMatchInlineSnapshot(
                `"2025-01-01T21:00:00.000+09:00"`
            )
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-02T14:00:00.000+09:00"`)
        })
    })

    describe('isResumingFromWaitUntilTimeWindow', () => {
        let handler: WaitUntilTimeWindowHandler

        beforeEach(() => {
            handler = new WaitUntilTimeWindowHandler()
        })

        it('should resume when time window has passed based on startedAtTimestamp, even if queueScheduledAt is set', () => {
            const actionStartedAt = DateTime.utc().set({ hour: 12, minute: 0 })
            const now = DateTime.utc().set({ hour: 15, minute: 30 })
            jest.setSystemTime(now.toJSDate())

            const invocation = {
                state: {
                    currentAction: {
                        id: 'wait_until_time_window',
                        startedAtTimestamp: actionStartedAt.toMillis(),
                    },
                },
                queueScheduledAt: now.plus({ days: 1 }), // Stale future time
            } as CyclotronJobInvocationHogFlow

            // Time window is 14:00-16:00, action started at 12:00, now is 15:30
            // Should resume because we're past the scheduled time (14:00) based on when action started
            const result = handler['isResumingFromWaitUntilTimeWindow'](invocation, action)
            expect(result).toBe(true)
        })

        it('should not resume when time window has not yet arrived based on startedAtTimestamp', () => {
            const actionStartedAt = DateTime.utc().set({ hour: 13, minute: 30 })
            const now = DateTime.utc().set({ hour: 13, minute: 45 })
            jest.setSystemTime(now.toJSDate())

            const invocation = {
                state: {
                    currentAction: {
                        id: 'wait_until_time_window',
                        startedAtTimestamp: actionStartedAt.toMillis(),
                    },
                },
                queueScheduledAt: now.plus({ hours: 1 }), // Future time
            } as CyclotronJobInvocationHogFlow

            // Time window is 14:00-16:00, action started at 13:30, now is 13:45
            // Should not resume because we're before the scheduled time (14:00)
            const result = handler['isResumingFromWaitUntilTimeWindow'](invocation, action)
            expect(result).toBe(false)
        })

        it('should resume when exactly at the window start time based on startedAtTimestamp', () => {
            const actionStartedAt = DateTime.utc().set({ hour: 12, minute: 0 })
            const now = DateTime.utc().set({ hour: 14, minute: 0 })
            jest.setSystemTime(now.toJSDate())

            const invocation = {
                state: {
                    currentAction: {
                        id: 'wait_until_time_window',
                        startedAtTimestamp: actionStartedAt.toMillis(),
                    },
                },
                queueScheduledAt: now.plus({ days: 1 }),
            } as CyclotronJobInvocationHogFlow

            // Time window is 14:00-16:00, action started at 12:00, now is exactly 14:00
            // Should resume because we're at or past the scheduled time
            const result = handler['isResumingFromWaitUntilTimeWindow'](invocation, action)
            expect(result).toBe(true)
        })

        it('should return false when startedAtTimestamp is missing', () => {
            const invocation = {
                state: {
                    currentAction: {
                        id: 'wait_until_time_window',
                        // No startedAtTimestamp
                    },
                },
            } as CyclotronJobInvocationHogFlow

            const result = handler['isResumingFromWaitUntilTimeWindow'](invocation, action)
            expect(result).toBe(false)
        })
    })

    describe('getWaitUntilTimeForAction', () => {
        it('should calculate wait time based on specific start time, not current time', () => {
            const handler = new WaitUntilTimeWindowHandler()
            const startTime = DateTime.utc().set({ hour: 10, minute: 0 })
            const now = DateTime.utc().set({ hour: 12, minute: 0 })
            jest.setSystemTime(now.toJSDate())

            const invocation = {
                state: {
                    currentAction: {
                        id: 'wait_until_time_window',
                        startedAtTimestamp: startTime.toMillis(),
                    },
                },
            } as CyclotronJobInvocationHogFlow

            // Should calculate based on 10:00 start time, not current time (12:00)
            // Time window is 14:00-16:00, so wait until 14:00
            const result = handler['isResumingFromWaitUntilTimeWindow'](invocation, action)
            expect(result).toBe(false)

            // Move time forward to 14:30
            jest.setSystemTime(DateTime.utc().set({ hour: 14, minute: 30 }).toJSDate())
            const result2 = handler['isResumingFromWaitUntilTimeWindow'](invocation, action)
            expect(result2).toBe(true)
        })

        it('should handle time window spanning midnight based on start time', () => {
            const handler = new WaitUntilTimeWindowHandler()
            action.config.time = ['23:00', '01:00']

            const startTime = DateTime.utc().set({ hour: 22, minute: 0 }) // 22:00
            const invocation = {
                state: {
                    currentAction: {
                        id: 'wait_until_time_window',
                        startedAtTimestamp: startTime.toMillis(),
                    },
                },
            } as CyclotronJobInvocationHogFlow

            // Before window (23:00)
            jest.setSystemTime(DateTime.utc().set({ hour: 22, minute: 30 }).toJSDate())
            expect(handler['isResumingFromWaitUntilTimeWindow'](invocation, action)).toBe(false)

            // In window (23:30)
            jest.setSystemTime(DateTime.utc().set({ hour: 23, minute: 30 }).toJSDate())
            expect(handler['isResumingFromWaitUntilTimeWindow'](invocation, action)).toBe(true)
        })
    })
})
