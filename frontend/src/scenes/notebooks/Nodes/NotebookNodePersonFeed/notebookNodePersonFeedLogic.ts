import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { posthog } from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { performQuery } from '~/queries/query'
import { NodeKind, SessionsTimelineQuery, SessionsTimelineQueryResponse } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { SessionSummary } from '~/types'

import type { notebookNodePersonFeedLogicType } from './notebookNodePersonFeedLogicType'

export type NotebookNodePersonFeedLogicProps = {
    personId: string
}

export const notebookNodePersonFeedLogic = kea<notebookNodePersonFeedLogicType>([
    props({} as NotebookNodePersonFeedLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'Nodes', 'notebookNodePersonFeedLogic', key]),
    key(({ personId }) => personId),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    actions({
        summarizeSessions: true,
        summarizeSession: (sessionId: string) => ({ sessionId }),
        setSummarizingState: (state: 'idle' | 'loading' | 'success' | 'error') => ({ state }),
    }),

    loaders(({ values, props }) => ({
        sessions: [
            null as SessionsTimelineQueryResponse['results'] | null,
            {
                loadSessionsTimeline: async () => {
                    const result = await performQuery<SessionsTimelineQuery>(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.SessionsTimelineQuery,
                            personId: props.personId,
                        })
                    )
                    return result.results
                },
            },
        ],
        summaries: [
            {} as Record<string, SessionSummary | 'error'>,
            {
                summarizeSession: async ({ sessionId }) => {
                    try {
                        const response = await api.sessionSummaries.createIndividual({
                            session_ids: [sessionId],
                        })
                        return { ...values.summaries, ...response }
                    } catch (error) {
                        posthog.captureException(error)
                        return { ...values.summaries, [sessionId]: 'error' }
                    }
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        summarizeSessions: async () => {
            values.sessionIdsWithRecording.forEach((sessionId) => actions.summarizeSession(sessionId))
        },
        summarizeSessionSuccess: () => {
            if (values.allSessionsSummarized) {
                actions.setSummarizingState('success')
            }
        },
    })),

    reducers({
        summarizingState: [
            'idle' as 'idle' | 'loading' | 'success' | 'error',
            {
                setSummarizingState: (_, { state }) => state,
                summarizeSessions: () => 'loading',
            },
        ],
    }),

    selectors({
        sessionIdsWithRecording: [
            (s) => [s.sessions],
            (sessions) =>
                sessions
                    ?.filter((session) => !!session.recording_duration_s)
                    .map((session) => session.sessionId)
                    .filter((id) => id !== undefined) as string[],
        ],
        canSummarize: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY]],
        allSessionsSummarized: [
            (s) => [s.summaries, s.sessionIdsWithRecording],
            (summaries, sessionIdsWithRecording) =>
                sessionIdsWithRecording.every((sessionId) => sessionId in summaries),
        ],
        hasErrors: [
            (s) => [s.summaries],
            (summaries) => Object.values(summaries).some((summary) => summary === 'error'),
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadSessionsTimeline()
    }),
])
