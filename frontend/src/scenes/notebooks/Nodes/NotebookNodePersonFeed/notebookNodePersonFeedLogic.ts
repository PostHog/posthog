import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { lazyLoaders, loaders } from 'kea-loaders'
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

    lazyLoaders(({ props }) => ({
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
    })),

    loaders(({ actions, values }) => ({
        sessionSummary: [
            null as SessionSummaryResponse | null,
            {
                summarizeSessions: async () => {
                    try {
                        actions.setSummarizingState('loading')
                        const sessionsWithRecordings = values?.sessions
                            ?.filter((session) => !!session.recording_duration_s)
                            .map((session) => session.sessionId)
                            .filter((id) => id !== undefined)
                        if (sessionsWithRecordings) {
                            return await api.sessionSummaries.create({
                                session_ids: sessionsWithRecordings,
                            })
                        }
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
            },
        ],
    }),

    selectors({
        canSummarize: [
            (s) => [s.featureFlags, s.sessions],
            (featureFlags, sessions) => featureFlags[FEATURE_FLAGS.AI_SESSION_SUMMARY] && sessions?.length > 0,
        ],
    }),

    listeners(({ actions }) => ({
        summarizeSessionsSuccess: () => {
            actions.setSummarizingState('success')
        },
        summarizeSessionsFailure: () => {
            actions.setSummarizingState('error')
        },
    })),
])
