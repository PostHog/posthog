import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'
import { RecordingComment } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'

import { CommentType, SessionRecordingId } from '~/types'

import type { sessionRecordingCommentsLogicType } from './sessionRecordingCommentsLogicType'
import { SessionRecordingMetaLogicProps, sessionRecordingMetaLogic } from './sessionRecordingMetaLogic'

export interface SessionRecordingCommentsLogicProps {
    sessionRecordingId: SessionRecordingId
}

export const sessionRecordingCommentsLogic = kea<sessionRecordingCommentsLogicType>([
    path((key) => ['scenes', 'session-recordings', 'sessionRecordingCommentsLogic', key]),
    props({} as SessionRecordingCommentsLogicProps),
    key(({ sessionRecordingId }) => sessionRecordingId || 'no-session-recording-id'),
    connect((props: SessionRecordingCommentsLogicProps) => {
        const metaLogic = sessionRecordingMetaLogic(props as SessionRecordingMetaLogicProps)
        return {
            actions: [metaLogic, ['loadRecordingMetaSuccess']],
        }
    }),
    actions({
        loadRecordingComments: true,
        loadRecordingNotebookComments: true,
    }),
    loaders(({ values, props }) => ({
        sessionComments: [
            [] as CommentType[],
            {
                loadRecordingComments: async (_, breakpoint): Promise<CommentType[]> => {
                    const empty: CommentType[] = []
                    if (!props.sessionRecordingId) {
                        return empty
                    }

                    try {
                        // Pass scope so Postgres can use the (team_id, scope, item_id, ...) composite index.
                        // All historical 'recording' comments were migrated to 'Replay' in migration 0870.
                        const response = await api.comments.list({
                            scope: 'Replay',
                            item_id: props.sessionRecordingId,
                        })
                        breakpoint()

                        return response.results || empty
                    } catch (e) {
                        // Users without resource-level access to comments get a 403 here. The replay scene
                        // side-loads comments unconditionally, so swallow the expected denial.
                        if (e instanceof ApiError && e.status === 403) {
                            return empty
                        }
                        throw e
                    }
                },
                deleteComment: async (id, breakpoint): Promise<CommentType[]> => {
                    await breakpoint(25)
                    await api.comments.delete(id)
                    return values.sessionComments.filter((sc) => sc.id !== id)
                },
            },
        ],
        sessionNotebookComments: {
            loadRecordingNotebookComments: async (_, breakpoint) => {
                const empty: RecordingComment[] = []
                if (!props.sessionRecordingId) {
                    return empty
                }

                try {
                    const response = await api.notebooks.recordingComments(props.sessionRecordingId)
                    breakpoint()

                    return response.results || empty
                } catch (e) {
                    // Users without resource-level access to notebooks get a 403 here. The replay scene
                    // side-loads notebook comments unconditionally, so swallow the expected denial.
                    if (e instanceof ApiError && e.status === 403) {
                        return empty
                    }
                    throw e
                }
            },
        },
    })),
    listeners(({ actions, props }) => ({
        loadRecordingMetaSuccess: () => {
            actions.loadRecordingComments()
            actions.loadRecordingNotebookComments()
        },

        deleteCommentSuccess: () => {
            lemonToast.success('Comment deleted')
        },

        deleteCommentFailure: (e) => {
            posthog.captureException(e, { action: 'session recording comments logic delete comment' })
            lemonToast.error('Could not delete comment, refresh and try again')
        },

        [playerCommentModel.actionTypes.commentEdited]: ({ recordingId }) => {
            if (props.sessionRecordingId === recordingId) {
                actions.loadRecordingComments()
            }
        },
    })),
])
