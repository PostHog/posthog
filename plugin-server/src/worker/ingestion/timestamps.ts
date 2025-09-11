import { DateTime, Duration } from 'luxon'

import { PluginEvent } from '@posthog/plugin-scaffold'

import { logger } from '../../utils/logger'
import { captureException } from '../../utils/posthog'

type IngestionWarningCallback = (type: string, details: Record<string, any>) => void

const FutureEventHoursCutoffMillis = 23 * 3600 * 1000 // 23 hours

export function parseEventTimestamp(data: PluginEvent, callback?: IngestionWarningCallback): DateTime {
    const now = DateTime.fromISO(data['now']).toUTC() // now is set by the capture endpoint and assumed valid

    let sentAt: DateTime | null = null
    if (!data.properties?.['$ignore_sent_at'] && data['sent_at']) {
        sentAt = DateTime.fromISO(data['sent_at']).toUTC()
        if (!sentAt.isValid) {
            callback?.('ignored_invalid_timestamp', {
                eventUuid: data['uuid'] ?? '',
                field: 'sent_at',
                value: data['sent_at'],
                reason: sentAt.invalidExplanation || 'unknown error',
            })
            sentAt = null
        }
    }

    let parsedTs = handleTimestamp(data, now, sentAt, data.team_id)

    // Events in the future would indicate an instrumentation bug, lets' ingest them
    // but publish an integration warning to help diagnose such issues.
    // We will also 'fix' the date to be now()
    const nowDiff = parsedTs.toUTC().diff(now).toMillis()
    if (nowDiff > FutureEventHoursCutoffMillis) {
        callback?.('event_timestamp_in_future', {
            timestamp: data['timestamp'] ?? '',
            sentAt: data['sent_at'] ?? '',
            offset: data['offset'] ?? '',
            now: data['now'],
            result: parsedTs.toISO(),
            eventUuid: data['uuid'],
            eventName: data['event'],
        })

        parsedTs = now
    }

    const parsedTsOutOfBounds = parsedTs.year < 0 || parsedTs.year > 9999
    if (!parsedTs.isValid || parsedTsOutOfBounds) {
        const details: Record<string, any> = {
            eventUuid: data['uuid'] ?? '',
            field: 'timestamp',
            value: data['timestamp'] ?? '',
            reason: parsedTs.invalidExplanation || (parsedTsOutOfBounds ? 'out of bounds' : 'unknown error'),
        }

        if (parsedTsOutOfBounds) {
            details['offset'] = data['offset']
            details['parsed_year'] = parsedTs.year
        }

        callback?.('ignored_invalid_timestamp', details)
        return DateTime.utc()
    }

    return parsedTs
}

function handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null, teamId: number): DateTime {
    let parsedTs: DateTime = now
    let timestamp: DateTime = now

    if (data['timestamp']) {
        timestamp = parseDate(data['timestamp'])

        if (!sentAt || !timestamp.isValid) {
            return timestamp
        }

        // To handle clock skew between the client and server, we attempt
        // to compute the skew based on the difference between the
        // client-generated `sent_at` and the server-generated `now`
        // filled by the capture endpoint.
        //
        // We calculate the skew as:
        //
        //      skew = sent_at - now
        //
        // And adjust the timestamp accordingly.

        // sent_at - timestamp == now - x
        // x = now + (timestamp - sent_at)
        try {
            // timestamp and sent_at must both be in the same format: either both with or both without timezones
            // otherwise we can't get a diff to add to now
            parsedTs = now.plus(timestamp.diff(sentAt))
        } catch (error) {
            logger.error('⚠️', 'Error when handling timestamp:', { error: error.message })
            captureException(error, {
                tags: { team_id: teamId },
                extra: { data, now, sentAt },
            })

            return timestamp
        }
    }

    if (data['offset']) {
        parsedTs = now.minus(Duration.fromMillis(data['offset']))
    }

    return parsedTs
}

export function parseDate(supposedIsoString: string): DateTime {
    const jsDate = new Date(supposedIsoString)
    if (Number.isNaN(jsDate.getTime())) {
        return DateTime.fromISO(supposedIsoString).toUTC()
    }
    return DateTime.fromJSDate(jsDate).toUTC()
}

export function toYearMonthDayInTimezone(
    timestamp: number,
    timeZone: string
): { year: number; month: number; day: number } {
    const parts = new Intl.DateTimeFormat('en', {
        timeZone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
    }).formatToParts(new Date(timestamp))
    const year = parts.find((part) => part.type === 'year')?.value
    const month = parts.find((part) => part.type === 'month')?.value
    const day = parts.find((part) => part.type === 'day')?.value
    if (!year || !month || !day) {
        throw new Error('Failed to get year, month, or day')
    }
    return { year: Number(year), month: Number(month), day: Number(day) }
}

export function toStartOfDayInTimezone(timestamp: number, timeZone: string): Date {
    const { year, month, day } = toYearMonthDayInTimezone(timestamp, timeZone)
    return DateTime.fromObject(
        { year, month, day, hour: 0, minute: 0, second: 0, millisecond: 0 },
        { zone: timeZone }
    ).toJSDate()
}
