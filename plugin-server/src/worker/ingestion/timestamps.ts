import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime, Duration } from 'luxon'

import { status } from '../../utils/status'

type InvalidTimestampCallback = (field: string, value: string, reason: string) => void

export function parseEventTimestamp(data: PluginEvent, callback?: InvalidTimestampCallback): DateTime {
    const now = DateTime.fromISO(data['now']).toUTC() // now is set by the capture endpoint and assumed valid

    let sentAt: DateTime | null = null
    if (data['sent_at']) {
        sentAt = DateTime.fromISO(data['sent_at']).toUTC()
        if (!sentAt.isValid) {
            callback?.('sent_at', data['sent_at'], sentAt.invalidExplanation || 'unknown error')
            sentAt = null
        }
    }

    const parsedTs = handleTimestamp(data, now, sentAt)
    if (!parsedTs.isValid) {
        callback?.('timestamp', data['timestamp'] ?? '', parsedTs.invalidExplanation || 'unknown error')
        return DateTime.utc()
    }
    return parsedTs
}

function handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null): DateTime {
    if (data['timestamp']) {
        const timestamp = parseDate(data['timestamp'])
        if (sentAt && timestamp.isValid) {
            // To handle clock skew on the timestamp sent by a client, we
            // attempt to calculate the skew based on the difference between the
            // client generated timestamp and the sent_at timestamp, which is
            // set on the client at point of posting to the capture endpoint.
            //
            // The capture endpoint also sets a `now` field which is the server
            // time, so we calculate the skew as:
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
