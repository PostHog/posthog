import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime, Duration } from 'luxon'

import { status } from '../../utils/status'

type InvalidTimestampCallback = (data: PluginEvent, reason: string) => void

export function parseEventTimestamp(data: PluginEvent, callback?: InvalidTimestampCallback): DateTime {
    const now = DateTime.fromISO(data['now']).toUTC()
    const sentAt = data['sent_at'] ? DateTime.fromISO(data['sent_at']).toUTC() : null

    const parsedTs = handleTimestamp(data, now, sentAt)
    if (!parsedTs.isValid) {
        callback?.(data, parsedTs.invalidExplanation ?? 'unknown')
        return DateTime.utc()
    }
    return parsedTs
}

function handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null): DateTime {
    if (data['timestamp']) {
        const timestamp = parseDate(data['timestamp'])
        if (sentAt && sentAt.isValid && timestamp.isValid) {
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
