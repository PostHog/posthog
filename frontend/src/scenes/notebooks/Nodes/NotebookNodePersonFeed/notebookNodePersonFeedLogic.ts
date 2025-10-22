import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { pluralize } from 'lib/utils'

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
        setSummarizingState: (state: 'idle' | 'loading' | 'completed') => ({ state }),
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
            {} as Record<string, SessionSummary>,
            {
                summarizeSession: async ({ sessionId }) => {
                    const response = await api.sessionSummaries.createIndividual({
                        session_ids: [sessionId],
                    })
                    return { ...values.summaries, ...response }
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        summarizeSessions: async () => {
            values.sessionIdsWithRecording.forEach((sessionId) => actions.summarizeSession(sessionId))
        },
        summarizeSessionSuccess: () => {
            if (values.numSummaries === values.numSessionsWithRecording) {
                actions.setSummarizingState('completed')
            }
        },
    })),

    reducers({
        summarizingState: [
            'idle' as 'idle' | 'loading' | 'completed',
            {
                setSummarizingState: (_, { state }) => state,
                summarizeSessions: () => 'loading',
            },
        ],
    }),

    selectors({
        canSummarize: [(s) => [s.featureFlags], (featureFlags) => featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY]],
        numSessionsWithRecording: [
            (s) => [s.sessionIdsWithRecording],
            (sessionIdsWithRecording) => sessionIdsWithRecording.length,
        ],
        numSummaries: [(s) => [s.summaries], (summaries) => Object.keys(summaries).length],
        progressText: [
            (s) => [s.numSummaries, s.numSessionsWithRecording],
            (numSummaries, numSessionsWithRecording) =>
                `${numSummaries} out of ${pluralize(numSessionsWithRecording, 'session')} analyzed.`,
        ],
        sessionIdsWithRecording: [
            (s) => [s.sessions],
            (sessions) =>
                sessions
                    ?.filter((session) => !!session.recording_duration_s)
                    .map((session) => session.sessionId)
                    .filter((id) => id !== undefined) as string[],
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadSessionsTimeline()
    }),
])
