import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime, Duration } from 'luxon'

import { status } from '../../utils/status'

type IngestionWarningCallback = (type: string, details: Record<string, any>) => void

const FutureEventHoursCutoffMillis = 23 * 3600 * 1000

export function parseEventTimestamp(data: PluginEvent, callback?: IngestionWarningCallback): DateTime {
    const now = DateTime.fromISO(data['now']).toUTC() // now is set by the capture endpoint and assumed valid

    let sentAt: DateTime | null = null
    if (data['sent_at']) {
        sentAt = DateTime.fromISO(data['sent_at']).toUTC()
        if (!sentAt.isValid) {
            callback?.('ignored_invalid_timestamp', {
                field: 'sent_at',
                value: data['sent_at'],
                reason: sentAt.invalidExplanation || 'unknown error',
            })
            sentAt = null
        }
    }

    const parsedTs = handleTimestamp(data, now, sentAt)
    if (!parsedTs.isValid) {
        callback?.('ignored_invalid_timestamp', {
            field: 'timestamp',
            value: data['timestamp'] ?? '',
            reason: parsedTs.invalidExplanation || 'unknown error',
        })
        return DateTime.utc()
    }

    // Events in the future would indicate an instrumentation bug, lets' ingest them
    // but publish an integration warning to help diagnose such issues.
    if (now.isValid && parsedTs.toUTC().diff(now).toMillis() > FutureEventHoursCutoffMillis) {
        callback?.('event_timestamp_in_future', {
            timestamp: data['timestamp'] ?? '',
            sentAt: data['sent_at'] ?? '',
            offset: data['offset'] ?? '',
            now: now,
            result: parsedTs.toISO(),
        })
    }
    return parsedTs
}

function handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null): DateTime {
    if (data['timestamp']) {
        const timestamp = parseDate(data['timestamp'])
        if (sentAt && timestamp.isValid) {
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
                return now.plus(timestamp.diff(sentAt))
            } catch (error) {
                status.error('⚠️', 'Error when handling timestamp:', { error: error.message })
                Sentry.captureException(error, { extra: { data, now, sentAt } })
            }
        }
        return timestamp
    }
    if (data['offset']) {
        return now.minus(Duration.fromMillis(data['offset']))
    }
    return now
}

export function parseDate(supposedIsoString: string): DateTime {
    const jsDate = new Date(supposedIsoString)
    if (Number.isNaN(jsDate.getTime())) {
        return DateTime.fromISO(supposedIsoString).toUTC()
    }
    return DateTime.fromJSDate(jsDate).toUTC()
}
