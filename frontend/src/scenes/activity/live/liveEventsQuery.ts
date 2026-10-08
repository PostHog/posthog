import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { LiveEvent } from '~/types'

export const LIVE_EVENTS_QUERY_POLL_MS = 10000

type LiveEventRow = [string, string, string, string, string | null, string | null]

export async function loadRecentLiveEvents(teamId: number, eventType: string | null): Promise<LiveEvent[]> {
    const response = await api.queryHogQL<LiveEventRow[]>(
        hogql`SELECT uuid, event, distinct_id, toString(timestamp), properties.$current_url, properties.$screen_name
            FROM events
            WHERE timestamp > now() - INTERVAL 5 MINUTE
              AND timestamp < now() + INTERVAL 1 MINUTE
              AND (${eventType ?? ''} = '' OR event = ${eventType ?? ''})
            ORDER BY timestamp DESC
            LIMIT 100`,
        { productKey: 'product_analytics', name: 'live_events_poll' },
        { refresh: 'force_blocking' }
    )
    return (response.results ?? []).map(([uuid, event, distinctId, timestamp, currentUrl, screenName]) => ({
        uuid,
        event,
        distinct_id: distinctId,
        timestamp,
        created_at: timestamp,
        team_id: teamId,
        properties: { $current_url: currentUrl, $screen_name: screenName },
    }))
}
