import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { pluralize } from 'lib/utils/strings'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SessionSummaryContent } from 'scenes/session-recordings/player/player-meta/types'

import { performQuery } from '~/queries/query'
import { NodeKind, SessionsTimelineQuery, SessionsTimelineQueryResponse } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from 'products/customer_analytics/frontend/constants'

import type { notebookNodePersonFeedLogicType } from './notebookNodePersonFeedLogicType'

export type NotebookNodePersonFeedLogicProps = {
    personId: string
}

export const notebookNodePersonFeedLogic = kea<notebookNodePersonFeedLogicType>([
    props({} as NotebookNodePersonFeedLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodePersonFeedLogic', key]),
    key(({ personId }) => personId),

    connect(() => ({
        values: [preflightLogic, ['isCloudOrDev']],
    })),

    actions({
        summarizeSessions: true,
        summarizeSession: (sessionId: string) => ({ sessionId }),
        setSummarizingState: (state: 'idle' | 'loading' | 'completed') => ({ state }),
    }),

    loaders(({ props }) => ({
        sessions: [
            null as SessionsTimelineQueryResponse['results'] | null,
            {
                loadSessionsTimeline: async () => {
                    const result = await performQuery<SessionsTimelineQuery>(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.SessionsTimelineQuery,
                            tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
                            personId: props.personId,
                        })
                    )
                    return result.results
                },
            },
        ],
        // Loader drives the per-session request and the summarizeSession{,Success,Failure} actions.
        // Accumulation lives in the `summaries` reducer below so concurrent requests can't race on a
        // read-modify-write of the shared map (the last response would otherwise clobber the others).
        sessionSummary: [
            null as Record<string, SessionSummaryContent> | null,
            {
                summarizeSession: async ({ sessionId }) => {
                    return await api.sessionSummaries.createIndividual({
                        session_ids: [sessionId],
                    })
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        summarizeSessions: async () => {
            values.sessionIdsWithRecording.forEach((sessionId) => actions.summarizeSession(sessionId))
        },
        summarizeSessionSuccess: () => {
            if (values.numProcessedSessions === values.numSessionsWithRecording) {
                actions.setSummarizingState('completed')
            }
        },
        summarizeSessionFailure: () => {
            if (values.numProcessedSessions === values.numSessionsWithRecording) {
                actions.setSummarizingState('completed')
            }
        },
    })),

    reducers(() => ({
        summaries: [
            {} as Record<string, SessionSummaryContent>,
            {
                summarizeSessionSuccess: (state, { sessionSummary }) => ({ ...state, ...sessionSummary }),
            },
        ],
        summarizingState: [
            'idle' as 'idle' | 'loading' | 'completed',
            {
                setSummarizingState: (_, { state }) => state,
                summarizeSessions: () => 'loading',
            },
        ],
        summaryErrors: [
            [] as string[],
            {
                summarizeSessionFailure: (state, { error }) => [...state, error],
            },
        ],
    })),

    selectors({
        // AI session summaries are PostHog Cloud only, so hide the whole block on self-hosted.
        canSummarize: [(s) => [s.isCloudOrDev], (isCloudOrDev): boolean => !!isCloudOrDev],
        numSessionsWithRecording: [
            (s) => [s.sessionIdsWithRecording],
            (sessionIdsWithRecording) => sessionIdsWithRecording.length,
        ],
        numSummaries: [(s) => [s.summaries], (summaries) => Object.keys(summaries).length],
        summariesLoading: [(s) => [s.sessionSummaryLoading], (sessionSummaryLoading) => sessionSummaryLoading],
        numFailedSummaries: [(s) => [s.summaryErrors], (summaryErrors) => summaryErrors.length],
        numProcessedSessions: [
            (s) => [s.numSummaries, s.numFailedSummaries],
            (numSummaries, numFailedSummaries) => numSummaries + numFailedSummaries,
        ],
        progressText: [
            (s) => [s.numProcessedSessions, s.numSessionsWithRecording],
            (numProcessedSessions, numSessionsWithRecording) =>
                `${numProcessedSessions} out of ${pluralize(numSessionsWithRecording, 'session')} analyzed.`,
        ],
        sessionIdsWithRecording: [
            (s) => [s.sessions],
            (sessions) =>
                (sessions
                    ?.filter((session) => !!session.recording_duration_s)
                    .map((session) => session.sessionId)
                    .filter((id) => id !== undefined) || []) as string[],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadSessionsTimeline()
    }),
])
