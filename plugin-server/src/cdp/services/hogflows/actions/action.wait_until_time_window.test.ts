import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlowAction } from '~/schema/hogflow'

import { HogFlowActionRunnerWaitUntilTimeWindow } from './action.wait_until_time_window'
import { findActionByType } from './utils'

describe('HogFlowActionRunnerWaitUntilTimeWindow', () => {
    let runner: HogFlowActionRunnerWaitUntilTimeWindow
    let action: Extract<HogFlowAction, { type: 'wait_until_time_window' }>

    beforeEach(() => {
        jest.useFakeTimers()
        jest.setSystemTime(new Date('2025-01-01T12:00:00.000Z')) // Wednesday at noon UTC

        runner = new HogFlowActionRunnerWaitUntilTimeWindow()
        const hogFlow = new FixtureHogFlowBuilder()
            .withWorkflow({
                actions: {
                    wait_until_time_window: {
                        type: 'wait_until_time_window',
                        config: {
                            timezone: 'UTC',
                            date: 'any',
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
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().set({ hour: 14, minute: 0, second: 0, millisecond: 0 }),
            })
        })

        it('should schedule immediately if current time is within window', () => {
            jest.setSystemTime(new Date('2025-01-01T15:00:00.000Z')) // Middle of window
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: undefined,
            })
        })

        it('should schedule for tomorrow if time window has passed', () => {
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // After time window
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 1 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 }),
            })
        })

        it('should handle "any" time', () => {
            action.config.time = 'any'
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 1 }).startOf('day'),
            })
        })

        it('should handle time window spanning midnight', () => {
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-01T22:00:00.000Z')) // Before window
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().set({ hour: 23, minute: 0, second: 0, millisecond: 0 }),
            })
        })

        it('should handle time window with minutes', () => {
            action.config.time = ['14:30', '15:45']
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().set({ hour: 14, minute: 30, second: 0, millisecond: 0 }),
            })
        })

        it('should handle time window with minutes when current time is within window', () => {
            action.config.time = ['14:30', '15:45']
            jest.setSystemTime(new Date('2025-01-01T15:00:00.000Z')) // Middle of window
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: undefined,
            })
        })
    })

    describe('date restrictions', () => {
        it('should handle weekday restriction', () => {
            action.config.date = 'weekday'
            jest.setSystemTime(new Date('2025-01-04T17:00:00.000Z')) // Saturday
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 2 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 }), // Monday
            })
        })

        it('should handle weekend restriction', () => {
            action.config.date = 'weekend'
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 3 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 }), // Saturday
            })
        })

        it('should handle specific days', () => {
            action.config.date = ['monday', 'wednesday', 'friday']
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 2 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 }), // Friday
            })
        })

        it('should handle single specific day', () => {
            action.config.date = ['monday']
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 5 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 }), // Monday
            })
        })

        it('should handle consecutive days', () => {
            action.config.date = ['monday', 'tuesday', 'wednesday']
            jest.setSystemTime(new Date('2025-01-01T17:00:00.000Z')) // Wednesday
            const result = runner.run(action)
            expect(result).toEqual({
                done: true,
                scheduledAt: DateTime.utc().plus({ days: 5 }).set({ hour: 14, minute: 0, second: 0, millisecond: 0 }), // Monday
            })
        })
    })

    describe('timezone handling', () => {
        it('should respect timezone setting', () => {
            action.config.timezone = 'America/New_York'
            const result = runner.run(action)
            // Compare to UTC for easier understanding
            expect(DateTime.utc().setZone('America/New_York').toISO()).toMatchInlineSnapshot(
                `"2025-01-01T07:00:00.000-05:00"`
            )
            expect(result.scheduledAt!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000-05:00"`)
            expect(result.done).toBe(true)
        })

        it('should handle timezone with DST', () => {
            action.config.timezone = 'America/New_York'
            jest.setSystemTime(new Date('2025-07-01T12:00:00.000Z')) // Summer time
            const result = runner.run(action)
            // Compare to UTC for easier understanding
            expect(DateTime.utc().setZone('America/New_York').toISO()).toMatchInlineSnapshot(
                `"2025-07-01T08:00:00.000-04:00"`
            )
            expect(result.scheduledAt!.toISO()).toMatchInlineSnapshot(`"2025-07-01T14:00:00.000-04:00"`)
            expect(result.done).toBe(true)
        })

        it('should handle timezone with negative offset', () => {
            action.config.timezone = 'Asia/Tokyo'

            const result = runner.run(action)
            // Compare to UTC for easier understanding
            expect(DateTime.utc().setZone('Asia/Tokyo').toISO()).toMatchInlineSnapshot(
                `"2025-01-01T21:00:00.000+09:00"`
            )
            expect(result.scheduledAt!.toISO()).toMatchInlineSnapshot(`"2025-01-02T14:00:00.000+09:00"`)
            expect(result.done).toBe(true)
        })
    })
})
