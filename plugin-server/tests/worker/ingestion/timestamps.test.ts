import { PluginEvent } from '@posthog/plugin-scaffold'
import { DateTime } from 'luxon'

import { parseDate, parseEventTimestamp } from '../../../src/worker/ingestion/timestamps'

describe('parseDate()', () => {
    const timestamps = [
        '2021-10-29',
        '2021-10-29 00:00:00',
        '2021-10-29 00:00:00.000000',
        '2021-10-29T00:00:00.000Z',
        '2021-10-29 00:00:00+00:00',
        '2021-10-29T00:00:00.000-00:00',
        '2021-10-29T00:00:00.000',
        '2021-10-29T00:00:00.000+00:00',
        '2021-W43-5',
        '2021-302',
    ]

    test.each(timestamps)('parses %s', (timestamp) => {
        const parsedTimestamp = parseDate(timestamp)
        expect(parsedTimestamp.year).toBe(2021)
        expect(parsedTimestamp.month).toBe(10)
        expect(parsedTimestamp.day).toBe(29)
        expect(parsedTimestamp.hour).toBe(0)
        expect(parsedTimestamp.minute).toBe(0)
        expect(parsedTimestamp.second).toBe(0)
        expect(parsedTimestamp.millisecond).toBe(0)
    })
})

describe('parseEventTimestamp()', () => {
    it('captures sent_at', () => {
        const rightNow = DateTime.utc()
        const tomorrow = rightNow.plus({ days: 1, hours: 2 })
        const tomorrowSentAt = rightNow.plus({ days: 1, hours: 2, minutes: 10 })

        const event = {
            timestamp: tomorrow.toISO(),
            now: rightNow,
            sent_at: tomorrowSentAt,
        } as any as PluginEvent

        const timestamp = parseEventTimestamp(event)
        const eventSecondsBeforeNow = rightNow.diff(timestamp, 'seconds').seconds

        expect(eventSecondsBeforeNow).toBeGreaterThan(590)
        expect(eventSecondsBeforeNow).toBeLessThan(610)
    })

    it('captures sent_at with no timezones', () => {
        const rightNow = DateTime.utc()
        const tomorrow = rightNow.plus({ days: 1, hours: 2 }).setZone('UTC+4')
        const tomorrowSentAt = rightNow.plus({ days: 1, hours: 2, minutes: 10 }).setZone('UTC+4')

        // TODO: not sure if this is correct?
        // tomorrow = tomorrow.replace(tzinfo=None)
        // tomorrow_sent_at = tomorrow_sent_at.replace(tzinfo=None)

        const event = {
            timestamp: tomorrow,
            now: rightNow,
            sent_at: tomorrowSentAt,
        } as any as PluginEvent

        const timestamp = parseEventTimestamp(event)
        const eventSecondsBeforeNow = rightNow.diff(timestamp, 'seconds').seconds

        expect(eventSecondsBeforeNow).toBeGreaterThan(590)
        expect(eventSecondsBeforeNow).toBeLessThan(610)
    })

    it('captures with no sent_at', () => {
        const rightNow = DateTime.utc()
        const tomorrow = rightNow.plus({ days: 1, hours: 2 })

        const event = {
            timestamp: tomorrow,
            now: rightNow,
        } as any as PluginEvent

        const timestamp = parseEventTimestamp(event)
        const difference = tomorrow.diff(timestamp, 'seconds').seconds
        expect(difference).toBeLessThan(1)
    })

    it('works with offset timestamp', () => {
        const now = DateTime.fromISO('2020-01-01T12:00:05.200Z')

        const event = {
            offset: 150,
            now,
            sent_at: now,
        } as any as PluginEvent

        const timestamp = parseEventTimestamp(event)
        expect(timestamp.toUTC().toISO()).toEqual('2020-01-01T12:00:05.050Z')
    })

    it('works with offset timestamp and no sent_at', () => {
        const now = DateTime.fromISO('2020-01-01T12:00:05.200Z')

        const event = {
            offset: 150,
            now,
        } as any as PluginEvent

        const timestamp = parseEventTimestamp(event)
        expect(timestamp.toUTC().toISO()).toEqual('2020-01-01T12:00:05.050Z')
    })
})
