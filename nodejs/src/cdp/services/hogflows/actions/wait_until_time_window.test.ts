import { DateTime } from 'luxon'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { HogFlowAction } from '~/cdp/schema/hogflow'
import { CyclotronPerson } from '~/cdp/types'

import { findActionByType } from '../hogflow-utils'
import { getWaitUntilTime, resolveTimezone } from './wait_until_time_window'

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

        it('should advance immediately for "any" time on a valid day', () => {
            action.config.time = 'any' // day is 'any', so today is always valid -> window is open now
            expect(getWaitUntilTime(action)).toBeNull()
        })

        it('should wait for the next valid day for "any" time when today is not valid', () => {
            jest.setSystemTime(new Date('2025-01-01T10:00:00.000Z')) // a Wednesday
            action.config.time = 'any'
            action.config.day = 'weekend'
            const result = getWaitUntilTime(action)
            expect(result).not.toBeNull()
            expect([6, 7]).toContain(result!.weekday) // Saturday or Sunday
        })

        it('should handle time window spanning midnight', () => {
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-01T22:00:00.000Z')) // Before window
            const result = getWaitUntilTime(action)
            expect(result).toEqual(DateTime.utc().set({ hour: 23, minute: 0, second: 0, millisecond: 0 }))
        })

        it('should advance immediately in the evening half of a window spanning midnight', () => {
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-01T23:30:00.000Z')) // Inside, before midnight
            expect(getWaitUntilTime(action)).toBeNull()
        })

        it('should advance immediately in the morning half of a window spanning midnight', () => {
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-02T00:30:00.000Z')) // Inside, after midnight
            expect(getWaitUntilTime(action)).toBeNull()
        })

        it('should wait for tonight when a window spanning midnight is not currently open', () => {
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-01T02:00:00.000Z')) // After last night's window, before tonight's
            expect(getWaitUntilTime(action)).toEqual(
                DateTime.utc().set({ hour: 23, minute: 0, second: 0, millisecond: 0 })
            )
        })

        it('anchors the morning half of a midnight-spanning window to the day it opened', () => {
            action.config.day = ['wednesday']
            action.config.time = ['23:00', '01:00']
            // Thursday 00:30 is still inside the window that opened Wednesday 23:00
            jest.setSystemTime(new Date('2025-01-02T00:30:00.000Z'))
            expect(getWaitUntilTime(action)).toBeNull()
        })

        it('handles the morning half of a spanning window in a non-UTC timezone', () => {
            action.config.timezone = 'America/New_York'
            action.config.time = ['23:00', '01:00']
            jest.setSystemTime(new Date('2025-01-15T05:30:00.000Z')) // 00:30 in New York
            expect(getWaitUntilTime(action)).toBeNull()
        })

        it('handles the morning half of a spanning window on a DST fall-back night', () => {
            action.config.timezone = 'America/New_York'
            action.config.time = ['23:00', '01:00']
            // 2025-11-02 is the US fall-back date; 04:30 UTC is 00:30 in New York, inside the window
            jest.setSystemTime(new Date('2025-11-02T04:30:00.000Z'))
            expect(getWaitUntilTime(action)).toBeNull()
        })

        it('handles the evening half of a spanning window on a DST spring-forward night', () => {
            action.config.timezone = 'America/New_York'
            action.config.time = ['23:00', '01:00']
            // 2025-03-09 is the US spring-forward date; 03:30 UTC on the 10th is 23:30 on the 9th in New York
            jest.setSystemTime(new Date('2025-03-10T03:30:00.000Z'))
            expect(getWaitUntilTime(action)).toBeNull()
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

    describe('person timezone handling', () => {
        const createPerson = (properties: Record<string, unknown>): CyclotronPerson => ({
            id: 'person-123',
            properties,
            name: 'Test Person',
            url: '/person/person-123',
        })

        it('should use person timezone when use_person_timezone is enabled', () => {
            action.config.use_person_timezone = true
            action.config.timezone = 'UTC'
            const person = createPerson({ $geoip_time_zone: 'America/New_York' })

            const result = getWaitUntilTime(action, person)
            // Person is in New York (UTC-5), so 14:00 EST
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000-05:00"`)
        })

        it('should fall back to fallback_timezone when person has no timezone', () => {
            action.config.use_person_timezone = true
            action.config.fallback_timezone = 'Europe/London'
            action.config.timezone = 'UTC'
            const person = createPerson({})

            const result = getWaitUntilTime(action, person)
            // Falls back to London timezone
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000+00:00"`)
        })

        it('should fall back to configured timezone when no fallback_timezone is set', () => {
            action.config.use_person_timezone = true
            action.config.fallback_timezone = null
            action.config.timezone = 'America/Chicago'
            const person = createPerson({})

            const result = getWaitUntilTime(action, person)
            // Falls back to Chicago timezone
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000-06:00"`)
        })

        it('should use configured timezone when use_person_timezone is false', () => {
            action.config.use_person_timezone = false
            action.config.timezone = 'America/Los_Angeles'
            const person = createPerson({ $geoip_time_zone: 'America/New_York' })

            const result = getWaitUntilTime(action, person)
            // Should use Los Angeles, ignoring person timezone
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000-08:00"`)
        })

        it('should handle person with null timezone property', () => {
            action.config.use_person_timezone = true
            action.config.fallback_timezone = 'Asia/Tokyo'
            const person = createPerson({ $geoip_time_zone: null })

            const result = getWaitUntilTime(action, person)
            // Falls back to Tokyo timezone
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-02T14:00:00.000+09:00"`)
        })

        it('should handle no person object when use_person_timezone is enabled', () => {
            action.config.use_person_timezone = true
            action.config.fallback_timezone = 'Europe/Paris'

            const result = getWaitUntilTime(action, undefined)
            // Falls back to Paris timezone
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000+01:00"`)
        })

        it('should fall back when person has invalid timezone', () => {
            action.config.use_person_timezone = true
            action.config.fallback_timezone = 'Europe/Berlin'
            const person = createPerson({ $geoip_time_zone: 'Invalid/Not_A_Timezone' })

            const result = getWaitUntilTime(action, person)
            // Falls back to Berlin timezone since person timezone is invalid
            expect(result!.toISO()).toMatchInlineSnapshot(`"2025-01-01T14:00:00.000+01:00"`)
        })
    })

    describe('resolveTimezone', () => {
        const createPerson = (properties: Record<string, unknown>): CyclotronPerson => ({
            id: 'person-123',
            properties,
            name: 'Test Person',
            url: '/person/person-123',
        })

        it.each([
            {
                name: 'uses person timezone when enabled and available',
                config: { use_person_timezone: true, timezone: 'UTC', fallback_timezone: null },
                person: { $geoip_time_zone: 'America/New_York' },
                expected: 'America/New_York',
            },
            {
                name: 'uses fallback when person has no timezone',
                config: { use_person_timezone: true, timezone: 'UTC', fallback_timezone: 'Europe/London' },
                person: {},
                expected: 'Europe/London',
            },
            {
                name: 'uses configured timezone as fallback when no fallback_timezone set',
                config: { use_person_timezone: true, timezone: 'America/Chicago', fallback_timezone: null },
                person: {},
                expected: 'America/Chicago',
            },
            {
                name: 'uses configured timezone when use_person_timezone is false',
                config: { use_person_timezone: false, timezone: 'Asia/Tokyo', fallback_timezone: null },
                person: { $geoip_time_zone: 'America/New_York' },
                expected: 'Asia/Tokyo',
            },
            {
                name: 'defaults to UTC when no timezone configured',
                config: { use_person_timezone: false, timezone: null, fallback_timezone: null },
                person: {},
                expected: 'UTC',
            },
            {
                name: 'handles undefined use_person_timezone as false',
                config: { timezone: 'Europe/Berlin', fallback_timezone: null },
                person: { $geoip_time_zone: 'America/New_York' },
                expected: 'Europe/Berlin',
            },
            {
                name: 'falls back when person timezone is invalid',
                config: { use_person_timezone: true, timezone: 'UTC', fallback_timezone: 'Europe/London' },
                person: { $geoip_time_zone: 'Invalid/Timezone' },
                expected: 'Europe/London',
            },
            {
                name: 'falls back to configured timezone when person timezone is invalid and no fallback set',
                config: { use_person_timezone: true, timezone: 'America/Chicago', fallback_timezone: null },
                person: { $geoip_time_zone: 'Not_A_Real_Zone' },
                expected: 'America/Chicago',
            },
            {
                name: 'falls back to UTC when person timezone is invalid and no fallback or timezone set',
                config: { use_person_timezone: true, timezone: null, fallback_timezone: null },
                person: { $geoip_time_zone: 'garbage' },
                expected: 'UTC',
            },
        ])('$name', ({ config, person, expected }) => {
            const fullConfig = {
                day: 'any' as const,
                time: 'any' as const,
                timezone: config.timezone,
                use_person_timezone: config.use_person_timezone,
                fallback_timezone: config.fallback_timezone,
            }
            const result = resolveTimezone(fullConfig, createPerson(person))
            expect(result).toBe(expected)
        })

        it('handles no person object', () => {
            const config = {
                day: 'any' as const,
                time: 'any' as const,
                timezone: 'America/Denver',
                use_person_timezone: true,
                fallback_timezone: 'Europe/Paris',
            }
            const result = resolveTimezone(config, undefined)
            expect(result).toBe('Europe/Paris')
        })
    })
})
