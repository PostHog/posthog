import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { isEmptyObject } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { userLogic } from 'scenes/userLogic'

import { sidePanelDiscussionLogic } from '~/layout/navigation-3000/sidepanel/panels/discussion/sidePanelDiscussionLogic'
import { CommentType } from '~/types'

import type { commentsLogicType } from './commentsLogicType'

export type CommentsLogicProps = {
    scope: CommentType['scope']
    item_id?: CommentType['item_id']
    item_context?: CommentType['item_context']
    disabled?: boolean
}

export type CommentWithRepliesType = {
    id: CommentType['id']
    comment?: CommentType // It may have been deleted
    replies: CommentType[]
}

export type CommentContext = {
    context: Record<string, any> | null
    callback?: (event: { sent: boolean }) => void
}

export const commentsLogic = kea<commentsLogicType>([
    path(() => ['scenes', 'notebooks', 'Notebook', 'commentsLogic']),
    props({} as CommentsLogicProps),
    key((props) => `${props.scope}-${props.item_id || ''}`),

    connect(() => ({
        actions: [sidePanelDiscussionLogic, ['incrementCommentCount']],
        values: [userLogic, ['user']],
    })),

    actions({
        loadComments: true,
        maybeLoadComments: true,
        setComposedComment: (content: string) => ({ content }),
        sendComposedContent: true,
        sendEmojiReaction: (emoji: string, sourceCommentId: string) => ({ emoji, sourceCommentId }),
        deleteComment: (comment: CommentType) => ({ comment }),
        setEditingComment: (comment: CommentType | null) => ({ comment }),
        setReplyingComment: (commentId: string | null) => ({ commentId }),
        setItemContext: (context: Record<string, any> | null, callback?: (event: { sent: boolean }) => void) => ({
            context,
            callback,
        }),
        clearItemContext: true,
        persistEditedComment: true,
        setComposerRef: (ref: HTMLTextAreaElement | null) => ({ ref }),
        focusComposer: true,
    }),
    reducers({
        replyingCommentId: [
            null as string | null,
            {
                setReplyingComment: (_, { commentId }) => commentId,
                sendComposedContentSuccess: () => null,
            },
        ],
        itemContext: [
            null as CommentContext | null,
            {
                setItemContext: (_, itemContext) => (itemContext.context ? itemContext : null),
                sendComposedContentSuccess: () => null,
            },
        ],
        editingComment: [
            null as CommentType | null,
            {
                setEditingComment: (_, { comment }) => comment,
                persistEditedCommentSuccess: () => null,
            },
        ],
        composedComment: [
            '',
            { persist: true },
            {
                setComposedComment: (_, { content }) => content,
                sendComposedContentSuccess: () => '',
            },
        ],
        composerRef: [
            null as HTMLTextAreaElement | null,
            {
                setComposerRef: (_, { ref }) => ref,
            },
        ],
    }),
    loaders(({ props, values, actions }) => ({
        comments: [
            null as CommentType[] | null,
            {
                loadComments: async () => {
                    const response = await api.comments.list({
                        scope: props.scope,
                        item_id: props.item_id,
                    })

                    return response.results
                },
                sendComposedContent: async () => {
                    const existingComments = values.comments ?? []

                    let itemContext: Record<string, any> | undefined = {
                        ...values.itemContext?.context,
                        ...props.item_context,
                    }
                    if (isEmptyObject(itemContext)) {
                        itemContext = undefined
                    }

                    const newComment = await api.comments.create({
                        content: values.composedComment,
                        scope: props.scope,
                        item_id: props.item_id,
                        item_context: itemContext,
                        source_comment: values.replyingCommentId ?? undefined,
                    })

                    values.itemContext?.callback?.({ sent: true })
                    return [...existingComments, newComment]
                },

                persistEditedComment: async () => {
                    const editedComment = values.editingComment
                    if (!editedComment) {
                        return values.comments
                    }

                    const existingComments = values.comments ?? []
                    const updatedComment = await api.comments.update(editedComment.id, {
                        content: editedComment.content,
                    })
                    return [...existingComments.filter((c) => c.id !== editedComment.id), updatedComment]
                },

                deleteComment: async ({ comment }) => {
                    await deleteWithUndo({
                        endpoint: `projects/@current/comments`,
                        object: { name: comment.item_context?.is_emoji ? 'Reaction' : 'Comment', id: comment.id },
                        callback: (isUndo) => {
                            if (isUndo) {
                                actions.loadCommentsSuccess([
                                    ...(values.comments?.filter((c) => c.id !== comment.id) ?? []),
                                    comment,
                                ])
                            }
                        },
                    })

                    return values.comments?.filter((c) => c.id !== comment.id) ?? null
                },

                sendEmojiReaction: async ({ emoji, sourceCommentId }) => {
                    const existingComments = values.comments ?? []

                    const newComment = await api.comments.create({
                        content: emoji,
                        scope: props.scope,
                        item_id: props.item_id,
                        source_comment: sourceCommentId,
                        item_context: {
                            is_emoji: true,
                        },
                    })

                    return [...existingComments, newComment]
                },
            },
        ],
    })),

    listeners(({ values, actions }) => ({
        setReplyingComment: () => {
            actions.clearItemContext()
        },
        clearItemContext: () => {
            values.itemContext?.callback?.({ sent: false })
            actions.setItemContext(null)
        },
        setItemContext: ({ context }) => {
            if (context) {
                values.composerRef?.focus()
            }
        },
        focusComposer: () => {
            values.composerRef?.focus()
        },
        maybeLoadComments: () => {
            if (!values.comments && !values.commentsLoading) {
                actions.loadComments()
            }
        },
        sendComposedContentSuccess: () => {
            actions.incrementCommentCount()
        },
    })),

    selectors({
        key: [() => [(_, props) => props], (props): string => `${props.scope}-${props.item_id || ''}`],
        sortedComments: [
            (s) => [s.comments],
            (comments) => {
                return comments?.sort((a, b) => (a.created_at > b.created_at ? 1 : -1)) ?? []
            },
        ],

        commentsWithReplies: [
            (s) => [s.sortedComments],
            (sortedComments) => {
                // NOTE: We build a tree of comments and replies here.
                // Comments may have been deleted so if we have a reply to a comment that no longer exists,
                // we still create the CommentWithRepliesType but with a null comment.

                const commentsById: Record<string, CommentWithRepliesType> = {}

                for (const comment of sortedComments ?? []) {
                    // Skip emoji reactions from the reply tree - they'll be handled separately
                    if (comment.item_context?.is_emoji) {
                        continue
                    }

                    let commentsWithReplies = commentsById[comment.source_comment ?? comment.id]

                    if (!commentsWithReplies) {
                        commentsById[comment.source_comment ?? comment.id] = commentsWithReplies = {
                            id: comment.source_comment ?? comment.id,
                            comment: undefined,
                            replies: [],
                        }
                    }

                    if (commentsWithReplies.id === comment.id) {
                        commentsWithReplies.comment = comment
                    } else {
                        commentsWithReplies.replies.push(comment)
                    }
                }

                return Object.values(commentsById)
            },
        ],

        emojiReactionsByComment: [
            (s) => [s.sortedComments],
            (sortedComments: CommentType[]) => {
                const reactions: Record<CommentType['id'], Record<string, CommentType[]>> = {}

                for (const comment of sortedComments ?? []) {
                    if (comment.item_context?.is_emoji && comment.source_comment) {
                        if (!reactions[comment.source_comment]) {
                            reactions[comment.source_comment] = {}
                        }
                        const emoji = comment.content
                        if (!reactions[comment.source_comment][emoji]) {
                            reactions[comment.source_comment][emoji] = []
                        }
                        reactions[comment.source_comment][emoji].push(comment)
                    }
                }

                return reactions
            },
        ],

        isMyComment: [
            (s) => [s.user],
            (user) => {
                return (comment: CommentType): boolean => comment.created_by?.uuid === user?.uuid
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        replyingCommentId: (value: string): void => {
            if (value) {
                actions.focusComposer()
            }
        },
    })),
])
