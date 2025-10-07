import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { JSONContent, RichContentEditorType } from 'lib/components/RichContentEditor/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { colonDelimitedDuration } from 'lib/utils'
import { playerCommentModel } from 'scenes/session-recordings/player/commenting/playerCommentModel'
import { isSingleEmoji } from 'scenes/session-recordings/utils'

import { CommentType } from '~/types'

import { SessionRecordingPlayerLogicProps, sessionRecordingPlayerLogic } from '../sessionRecordingPlayerLogic'
import type { playerCommentOverlayLogicType } from './playerFrameCommentOverlayLogicType'

export interface RecordingCommentForm {
    // formatted time in recording, e.g. 00:00:00, 00:00:01, 00:00:02, etc.
    // this is a string because we want to be able to display the time in the recording
    timeInRecording?: string | null
    // number of seconds into recording
    timestampInRecording?: number | null
    // the date that the timeInRecording represents
    dateForTimestamp?: Dayjs | null
    content: string
    richContent: JSONContent | null
    recordingId: string | null
    commentId: CommentType['id'] | null
}

export interface PlayerCommentOverlayLogicProps extends SessionRecordingPlayerLogicProps {
    recordingId: string
}

export const playerCommentOverlayLogic = kea<playerCommentOverlayLogicType>([
    path(['scenes', 'session-recordings', 'player', 'PlayerFrameAnnotationOverlay']),
    key((props) => props.recordingId ?? 'unknown'),
    props({} as PlayerCommentOverlayLogicProps),
    connect((props: PlayerCommentOverlayLogicProps) => ({
        values: [sessionRecordingPlayerLogic(props), ['currentPlayerTime', 'currentTimestamp', 'sessionPlayerData']],
        actions: [sessionRecordingPlayerLogic(props), ['setIsCommenting']],
    })),
    actions({
        editComment: (comment: RecordingCommentForm) => ({ comment }),
        addEmojiComment: (emoji: string) => ({ emoji }),
        setLoading: (isLoading: boolean) => ({ isLoading }),
        setRichContent: (richContent: JSONContent | null) => ({ richContent }),
        // copied from comments logic
        setRichContentEditor: (editor: RichContentEditorType) => ({ editor }),
        onRichContentEditorUpdate: (isEmpty: boolean) => ({ isEmpty }),
    }),
    reducers({
        isLoading: [
            false,
            {
                setLoading: (_, { isLoading }: { isLoading: boolean }) => isLoading,
            },
        ],

        // copied from comments logic
        isEmpty: [
            true as boolean,
            {
                onRichContentEditorUpdate: (_, { isEmpty }) => isEmpty,
            },
        ],
        richContentEditor: [
            null as RichContentEditorType | null,
            {
                setRichContentEditor: (_, { editor }) => editor,
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
        setRichContent: ({ richContent }) => {
            actions.setRecordingCommentValue('richContent', richContent)
        },
        editComment: ({ comment }) => {
            actions.setRecordingCommentValue('content', comment.content)
            actions.setRecordingCommentValue('richContent', comment.richContent)
            actions.setRecordingCommentValue('recordingId', comment.recordingId)
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
                    scope: 'Replay',
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
                richContent: null,
                recordingId: null,
                commentId: null,
            } as RecordingCommentForm,
            errors: ({ content, richContent }) => {
                return {
                    content:
                        !content?.trim() && !Object.keys(richContent ?? {}).length
                            ? 'A comment must have some content.'
                            : null,
                }
            },
            submit: async (data) => {
                const { commentId, content, richContent, dateForTimestamp } = data

                if (!dateForTimestamp) {
                    throw new Error('Cannot comment without a timestamp.')
                }

                const apiPayload = {
                    content,
                    rich_content: richContent,
                    scope: 'Replay',
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
