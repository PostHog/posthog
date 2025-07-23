import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { colonDelimitedDuration } from 'lib/utils'

import { CommentType } from '~/types'

import type { playerCommentOverlayLogicType } from './playerFrameCommentOverlayLogicType'
import { sessionRecordingPlayerLogic, SessionRecordingPlayerLogicProps } from '../sessionRecordingPlayerLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { isSingleEmoji } from 'scenes/session-recordings/utils'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'

export interface RecordingCommentForm {
    // formatted time in recording, e.g. 00:00:00, 00:00:01, 00:00:02, etc.
    // this is a string because we want to be able to display the time in the recording
    timeInRecording: string | null
    // number of seconds into recording
    timestampInRecording?: number | null
    // the date that the timeInRecording represents
    dateForTimestamp?: Dayjs | null
    content: string
    recordingId: string | null
    commentId: CommentType['id'] | null
}

export interface PlayerCommentOverlayLogicProps extends SessionRecordingPlayerLogicProps {
    recordingId: string
}

export const playerCommentOverlayLogic = kea<playerCommentOverlayLogicType>([
    path(['scenes', 'session-recordings', 'player', 'PlayerFrameAnnotationOverlay']),
    props({} as PlayerCommentOverlayLogicProps),
    connect((props: PlayerCommentOverlayLogicProps) => ({
        values: [sessionRecordingPlayerLogic(props), ['currentPlayerTime', 'currentTimestamp', 'sessionPlayerData']],
        actions: [sessionRecordingPlayerLogic(props), ['setIsCommenting']],
    })),
    actions({
        editComment: (comment: RecordingCommentForm) => ({ comment }),
        addEmojiComment: (emoji: string) => ({ emoji }),
        setLoading: (isLoading: boolean) => ({ isLoading }),
    }),
    reducers({
        isLoading: [
            false,
            {
                setLoading: (_, { isLoading }: { isLoading: boolean }) => isLoading,
            },
        ],
    }),
    selectors({
        timestampUnits: [
            (s) => [s.sessionPlayerData],
            (sessionPlayerData) => {
                const endTimeSeconds = Math.floor(sessionPlayerData.durationMs / 1000)
                return endTimeSeconds > 3600 ? 3 : 2
            },
        ],
        formattedTimestamp: [
            (s) => [s.currentPlayerTime, s.timestampUnits],
            (currentPlayerTime, timestampUnits) => {
                return colonDelimitedDuration(currentPlayerTime / 1000, timestampUnits)
            },
        ],
    }),
    subscriptions(({ actions, values }) => ({
        formattedTimestamp: (formattedTimestamp) => {
            // as the timestamp from the player changes we track three representations of it
            actions.setRecordingCommentValue('timeInRecording', formattedTimestamp)
            actions.setRecordingCommentValue('timestampInRecording', values.currentPlayerTime)
            actions.setRecordingCommentValue('dateForTimestamp', dayjs(values.currentTimestamp))
        },
    })),
    listeners(({ actions, props, values }) => ({
        editComment: ({ comment }) => {
            actions.setRecordingCommentValue('content', comment.content)
            actions.setRecordingCommentValue('recordingId', comment.recordingId)
            // don't change the scope if it has one
            actions.setRecordingCommentValue('scope', 'recording')
            actions.setRecordingCommentValue('commentId', comment.commentId)
            // opening to edit also sets the player timestamp, which will update the timestamps in the form
            actions.setIsCommenting(true)
        },
        setIsCommenting: ({ isCommenting }) => {
            if (!isCommenting) {
                actions.resetRecordingComment()
            }
        },
        addEmojiComment: async ({ emoji }) => {
            if (!isSingleEmoji(emoji)) {
                lemonToast.error(`Emoji comments must be emojis 🙈, this string was too long: "${emoji}"`)
                return
            }
            const loadingTimeout = setTimeout(() => {
                actions.setLoading(true)
            }, 250)

            try {
                await api.comments.create({
                    content: emoji,
                    scope: 'recording',
                    item_id: props.recordingId,
                    item_context: {
                        is_emoji: true,
                        time_in_recording: dayjs(values.currentTimestamp).toISOString(),
                    },
                })
                playerCommentModel.actions.commentEdited(props.recordingId)
            } finally {
                if (loadingTimeout) {
                    clearTimeout(loadingTimeout)
                }
                actions.setLoading(false)
            }
        },
    })),
    forms(({ props, values, actions }) => ({
        recordingComment: {
            defaults: {
                timeInRecording: values.formattedTimestamp ?? '00:00:00',
                dateForTimestamp: null,
                content: '',
                recordingId: null,
                commentId: null,
            } as RecordingCommentForm,
            errors: ({ content }) => ({
                content: !content?.trim()
                    ? 'A comment must have text content.'
                    : content.length > 400
                    ? 'Must be 400 characters or less'
                    : null,
            }),
            submit: async (data) => {
                const { commentId, content, dateForTimestamp } = data

                if (!dateForTimestamp) {
                    throw new Error('Cannot comment without a timestamp.')
                }

                const apiPayload = {
                    content,
                    scope: 'recording',
                    item_id: props.recordingId,
                    item_context: {
                        time_in_recording: dateForTimestamp.toISOString(),
                    },
                }
                if (commentId) {
                    await api.comments.update(commentId, apiPayload)
                } else {
                    await api.comments.create(apiPayload)
                }

                playerCommentModel.actions.commentEdited(props.recordingId)
                actions.resetRecordingComment()
                actions.setIsCommenting(false)
            },
        },
    })),
])
