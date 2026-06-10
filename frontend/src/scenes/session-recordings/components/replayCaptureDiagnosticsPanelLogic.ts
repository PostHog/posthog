import { defaults, kea, key, path, props } from 'kea'
import { lazyLoaders } from 'kea-loaders'

import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'

import { hogql } from '~/queries/utils'

import type { replayCaptureDiagnosticsPanelLogicType } from './replayCaptureDiagnosticsPanelLogicType'

export interface ReplayCaptureDiagnosticsPanelLogicProps {
    sessionId: string
}

const UUIDV7_SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// posthog-js sessions last at most 24 hours, but the session id's embedded
// timestamp comes from the client clock while event timestamps are
// server-corrected, so allow a few days of slack either side.
const CLOCK_SKEW_SLACK_DAYS = 3
const MAX_SESSION_DURATION_DAYS = 1

// Fallback window for session ids that don't parse as UUIDv7, or when the
// bounded window returns no results (e.g. severe client clock skew): wide
// enough to cover any session within the default retention period.
const FALLBACK_LOOKBACK_DAYS = 90

// UUIDv7 session ids were introduced after PostHog's GA; any embedded year
// before this is implausible and indicates a corrupt or pre-epoch timestamp.
const EARLIEST_PLAUSIBLE_SESSION_YEAR = 2020

export function sessionIdTimestampBounds(sessionId: string, now: Dayjs = dayjs()): { from: Dayjs; to: Dayjs } {
    if (UUIDV7_SESSION_ID.test(sessionId)) {
        const sessionStart = dayjs(parseInt(sessionId.replaceAll('-', '').slice(0, 12), 16))
        const plausible =
            sessionStart.isValid() &&
            sessionStart.year() >= EARLIEST_PLAUSIBLE_SESSION_YEAR &&
            sessionStart.isBefore(now.add(1, 'day'))
        if (plausible) {
            return {
                from: sessionStart.subtract(CLOCK_SKEW_SLACK_DAYS, 'day'),
                to: sessionStart.add(MAX_SESSION_DURATION_DAYS + CLOCK_SKEW_SLACK_DAYS, 'day'),
            }
        }
    }
    return { from: now.subtract(FALLBACK_LOOKBACK_DAYS, 'day'), to: now.add(1, 'day') }
}

export function fallbackSessionTimestampBounds(now: Dayjs = dayjs()): { from: Dayjs; to: Dayjs } {
    return { from: now.subtract(FALLBACK_LOOKBACK_DAYS, 'day'), to: now.add(1, 'day') }
}

export const replayCaptureDiagnosticsPanelLogic = kea<replayCaptureDiagnosticsPanelLogicType>([
    path(['scenes', 'session-recordings', 'components', 'replayCaptureDiagnosticsPanelLogic']),
    props({} as ReplayCaptureDiagnosticsPanelLogicProps),
    key((props) => props.sessionId),
    defaults({
        sessionEventProperties: null as Record<string, any> | null,
    }),
    lazyLoaders(({ props }) => ({
        sessionEventProperties: {
            loadSessionEventProperties: async (_, breakpoint): Promise<Record<string, any> | null> => {
                // The timestamp bounds let the events sort key prune the scan;
                // without them this single-session lookup reads the team's
                // entire event history.
                const fetchWithin = async ({
                    from,
                    to,
                }: {
                    from: Dayjs
                    to: Dayjs
                }): Promise<Record<string, any> | null> => {
                    const query = hogql`
SELECT properties
FROM events
WHERE $session_id = ${props.sessionId}
AND timestamp >= ${from}
AND timestamp <= ${to}
ORDER BY timestamp DESC
LIMIT 1`
                    const result = await api.queryHogQL(query, {
                        scene: 'ReplayCaptureDiagnostics',
                        productKey: 'session_replay',
                    })
                    breakpoint()
                    const row = result?.results?.[0]?.[0]
                    if (!row) {
                        return null
                    }
                    return typeof row === 'string' ? JSON.parse(row) : row
                }

                const bounds = sessionIdTimestampBounds(props.sessionId)
                const properties = await fetchWithin(bounds)
                if (properties !== null) {
                    return properties
                }

                // A UUIDv7-derived window comes from the client clock, so a badly
                // skewed clock can place it outside the session's server-corrected
                // timestamps and the tight query finds nothing. Widen to the
                // retention fallback before giving up so a skewed clock degrades to
                // slower-but-correct rather than fast-but-blank. Only worth retrying
                // when the first window was actually narrower than the fallback.
                const fallback = fallbackSessionTimestampBounds()
                if (!bounds.from.isAfter(fallback.from)) {
                    return null
                }
                return fetchWithin(fallback)
            },
        },
    })),
])
