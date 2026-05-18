/**
 * HACK companion to `services/agent-core/src/session-logs/`. Polls a single
 * session's timeline (assistant messages + tool calls + tool results + runner
 * logs) via a Django JSON proxy backed by a 1h Redis buffer. Replaced once
 * loki/clickhouse is wired up. Streaming variant was 406'd by DRF content
 * negotiation — polling is dumb but works.
 */
import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import type { sessionLogsLogicType } from './sessionLogsLogicType'

export interface SessionLogEventEntry {
    kind: 'event'
    type: string
    at: string
    [k: string]: unknown
}

export interface SessionLogLogEntry {
    kind: 'log'
    level: 'debug' | 'info' | 'warn' | 'error'
    at: string
    message: string
    extra?: Record<string, unknown>
}

export type SessionLogEntry = SessionLogEventEntry | SessionLogLogEntry

export interface SessionLogsLogicProps {
    applicationSlug: string
    sessionId: string
}

const POLL_INTERVAL_MS = 2_000

export const sessionLogsLogic = kea<sessionLogsLogicType>([
    path((key) => ['products', 'agent_stack', 'sessionLogsLogic', key]),
    props({} as SessionLogsLogicProps),
    key((props) => `${props.applicationSlug}:${props.sessionId}`),

    actions({
        start: true,
        stop: true,
        fetchNow: true,
        setEntries: (entries: SessionLogEntry[]) => ({ entries }),
        setError: (error: string | null) => ({ error }),
        setLoading: (loading: boolean) => ({ loading }),
    }),

    reducers({
        entries: [
            [] as SessionLogEntry[],
            {
                setEntries: (_, { entries }) => entries,
            },
        ],
        loading: [
            false,
            {
                setLoading: (_, { loading }) => loading,
            },
        ],
        error: [
            null as string | null,
            {
                setError: (_, { error }) => error,
            },
        ],
    }),

    selectors({
        url: [
            () => [
                teamLogic.selectors.currentTeamId,
                (_, props: SessionLogsLogicProps) => props.applicationSlug,
                (_, props: SessionLogsLogicProps) => props.sessionId,
            ],
            (teamId, slug, sessionId) =>
                `/api/projects/${teamId}/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/logs/`,
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        start: () => {
            if (cache.timer) {
                return
            }
            actions.fetchNow()
            cache.timer = window.setInterval(() => actions.fetchNow(), POLL_INTERVAL_MS)
        },
        stop: () => {
            if (cache.timer) {
                window.clearInterval(cache.timer)
                cache.timer = undefined
            }
        },
        fetchNow: async () => {
            actions.setLoading(true)
            try {
                const resp = await fetch(values.url, { credentials: 'include' })
                if (!resp.ok) {
                    actions.setError(`http ${resp.status}`)
                    return
                }
                const body = (await resp.json()) as { entries?: SessionLogEntry[] }
                actions.setEntries(body.entries ?? [])
                actions.setError(null)
            } catch (err) {
                actions.setError(String(err))
            } finally {
                actions.setLoading(false)
            }
        },
    })),
])
