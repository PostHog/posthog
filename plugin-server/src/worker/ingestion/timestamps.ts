import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { StatsD } from 'hot-shots'
import { DateTime, Duration } from 'luxon'

import { status } from '../../utils/status'

export function parseEventTimestamp(data: PluginEvent, statsd?: StatsD | undefined): DateTime {
    const now = DateTime.fromISO(data['now'])
    const sentAt = data['sent_at'] ? DateTime.fromISO(data['sent_at']) : null

    const parsedTs = handleTimestamp(data, now, sentAt)
    const ts = parsedTs.isValid ? parsedTs : DateTime.now()
    if (!parsedTs.isValid) {
        statsd?.increment('process_event_invalid_timestamp', { teamId: String(data['team_id']) })
    }
    return ts
}

function handleTimestamp(data: PluginEvent, now: DateTime, sentAt: DateTime | null): DateTime {
    if (data['timestamp']) {
        if (sentAt) {
            // sent_at - timestamp == now - x
            // x = now + (timestamp - sent_at)
            try {
                // timestamp and sent_at must both be in the same format: either both with or both without timezones
                // otherwise we can't get a diff to add to now
                return now.plus(parseDate(data['timestamp']).diff(sentAt))
            } catch (error) {
                status.error('⚠️', 'Error when handling timestamp:', error)
                Sentry.captureException(error, { extra: { data, now, sentAt } })
            }
        }
        return parseDate(data['timestamp'])
    }
    if (data['offset']) {
        return now.minus(Duration.fromMillis(data['offset']))
    }
    return now
}

export function parseDate(supposedIsoString: string): DateTime {
    const jsDate = new Date(supposedIsoString)
    if (Number.isNaN(jsDate.getTime())) {
        return DateTime.fromISO(supposedIsoString)
    }
    return DateTime.fromJSDate(jsDate)
}
