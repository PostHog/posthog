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

// Fallback window for session ids that don't parse as UUIDv7: wide enough to
// cover any session whose recording could still be within retention.
const FALLBACK_LOOKBACK_DAYS = 90

export function sessionIdTimestampBounds(sessionId: string, now: Dayjs = dayjs()): { from: Dayjs; to: Dayjs } {
    if (UUIDV7_SESSION_ID.test(sessionId)) {
        const sessionStart = dayjs(parseInt(sessionId.replaceAll('-', '').slice(0, 12), 16))
        const plausible =
            sessionStart.isValid() && sessionStart.year() >= 2020 && sessionStart.isBefore(now.add(1, 'day'))
        if (plausible) {
            return {
                from: sessionStart.subtract(CLOCK_SKEW_SLACK_DAYS, 'day'),
                to: sessionStart.add(MAX_SESSION_DURATION_DAYS + CLOCK_SKEW_SLACK_DAYS, 'day'),
            }
        }
    }
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
                const { from, to } = sessionIdTimestampBounds(props.sessionId)
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
            },
        },
    })),
])
