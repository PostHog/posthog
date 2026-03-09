import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import api from '~/lib/api'
import { NodeKind, TracesQuery } from '~/queries/schema/schema-general'

import type { aiConversationsPanelLogicType } from './aiConversationsPanelLogicType'

export interface AIConversationsPanelLogicProps {
    personId: string
    ticketCreatedAt: string
}

export interface AISession {
    sessionId: string
    traceId: string
    createdAt: string
}

const MAX_DISPLAY = 5

export const aiConversationsPanelLogic = kea<aiConversationsPanelLogicType>([
    path(['products', 'conversations', 'frontend', 'scenes', 'ticket', 'aiConversationsPanelLogic']),
    props({} as AIConversationsPanelLogicProps),
    key((props) => `${props.personId}-${props.ticketCreatedAt}`),

    actions({
        loadSessions: true,
        setSessionsResult: (sessions: AISession[], totalCount: number) => ({ sessions, totalCount }),
        setSessionsLoading: (loading: boolean) => ({ loading }),
    }),

    reducers({
        sessions: [
            [] as AISession[],
            {
                setSessionsResult: (_, { sessions }) => sessions,
            },
        ],
        totalCount: [
            0,
            {
                setSessionsResult: (_, { totalCount }) => totalCount,
            },
        ],
        sessionsLoading: [
            false,
            {
                loadSessions: () => true,
                setSessionsResult: () => false,
                setSessionsLoading: (_, { loading }) => loading,
            },
        ],
    }),

    listeners(({ actions, props }) => ({
        loadSessions: async () => {
            try {
                const ticketDate = new Date(props.ticketCreatedAt)
                const dateFrom = new Date(ticketDate.getTime() - 7 * 24 * 60 * 60 * 1000).toISOString()
                const dateTo = new Date(ticketDate.getTime() + 1 * 24 * 60 * 60 * 1000).toISOString()

                // Use TracesQuery with personId — the native query node for LLM trace data.
                // This avoids raw HogQL and uses the same infrastructure as the LLM analytics product.
                const query: TracesQuery = {
                    kind: NodeKind.TracesQuery,
                    personId: props.personId,
                    dateRange: {
                        date_from: dateFrom,
                        date_to: dateTo,
                    },
                    limit: 50,
                }

                const response = await api.query(query)
                const traces = response.results || []

                // Group traces by session, keeping the earliest timestamp per session
                const sessionMap = new Map<string, AISession>()
                for (const trace of traces) {
                    const sessionId = trace.aiSessionId
                    if (!sessionId) {
                        continue
                    }
                    const existing = sessionMap.get(sessionId)
                    if (!existing || trace.createdAt < existing.createdAt) {
                        sessionMap.set(sessionId, {
                            sessionId,
                            traceId: trace.id,
                            createdAt: trace.createdAt,
                        })
                    }
                }

                // Sort by proximity to ticket creation (closest first)
                const ticketMs = ticketDate.getTime()
                const allSessions = Array.from(sessionMap.values()).sort((a, b) => {
                    const aDiff = Math.abs(new Date(a.createdAt).getTime() - ticketMs)
                    const bDiff = Math.abs(new Date(b.createdAt).getTime() - ticketMs)
                    return aDiff - bDiff
                })

                actions.setSessionsResult(allSessions.slice(0, MAX_DISPLAY), allSessions.length)
            } catch (error) {
                console.error('Failed to load AI conversations:', error)
                actions.setSessionsLoading(false)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSessions()
    }),
])
