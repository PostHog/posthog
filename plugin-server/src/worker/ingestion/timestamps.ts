import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime, Duration } from 'luxon'

import { status } from '../../utils/status'

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

    if (!parsedTs.isValid) {
        callback?.('ignored_invalid_timestamp', {
            eventUuid: data['uuid'] ?? '',
            field: 'timestamp',
            value: data['timestamp'] ?? '',
            reason: parsedTs.invalidExplanation || 'unknown error',
        })
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
            status.error('⚠️', 'Error when handling timestamp:', { error: error.message })
            Sentry.captureException(error, {
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
