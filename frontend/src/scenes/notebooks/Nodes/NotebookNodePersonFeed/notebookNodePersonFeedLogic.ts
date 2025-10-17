import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { performQuery } from '~/queries/query'
import { NodeKind, SessionsTimelineQuery, SessionsTimelineQueryResponse } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { SessionSummaryResponse } from '~/types'

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
        setSummarizingState: (state: 'idle' | 'loading' | 'success' | 'error') => ({ state }),
    }),

    loaders(({ actions, values, props }) => ({
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
        sessionSummary: [
            null as SessionSummaryResponse | null,
            {
                summarizeSessions: async () => {
                    try {
                        actions.setSummarizingState('loading')
                        if (values.sessionIdsWithRecording.length === 0) {
                            return null
                        }

                        const response = await api.sessionSummaries.create({
                            session_ids: values.sessionIdsWithRecording,
                        })
                        return response
                    } catch (error) {
                        posthog.captureException(error)
                        throw error
                    }
                },
            },
        ],
    })),

    reducers({
        summarizingState: [
            'idle' as 'idle' | 'loading' | 'success' | 'error',
            {
                setSummarizingState: (_, { state }) => state,
                summarizeSessionsSuccess: () => 'success',
                summarizeSessionsFailure: () => 'error',
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
    }),

    afterMount(({ actions }) => {
        actions.loadSessionsTimeline()
    }),
])
