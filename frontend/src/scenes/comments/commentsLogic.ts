import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { RichContentEditorType } from 'lib/components/RichContentEditor/types'
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
        focusComposer: true,
        clearItemContext: true,
        maybeLoadComments: true,
        sendComposedContent: true,
        persistEditedComment: true,
        onRichContentEditorUpdate: (isEmpty: boolean) => ({ isEmpty }),
        onEditingCommentRichContentEditorUpdate: (isEmpty: boolean) => ({ isEmpty }),
        sendEmojiReaction: (emoji: string, sourceCommentId: string) => ({ emoji, sourceCommentId }),
        deleteComment: (comment: CommentType) => ({ comment }),
        setEditingComment: (comment: CommentType | null) => ({ comment }),
        setReplyingComment: (commentId: string | null) => ({ commentId }),
        setItemContext: (context: Record<string, any> | null, callback?: (event: { sent: boolean }) => void) => ({
            context,
            callback,
        }),
        setRichContentEditor: (editor: RichContentEditorType) => ({ editor }),
        setEditingCommentRichContentEditor: (editor: RichContentEditorType | null) => ({ editor }),
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
        richContentEditor: [
            null as RichContentEditorType | null,
            {
                setRichContentEditor: (_, { editor }) => editor,
            },
        ],
        isEmpty: [
            true as boolean,
            {
                onRichContentEditorUpdate: (_, { isEmpty }) => isEmpty,
            },
        ],
        editingComment: [
            null as CommentType | null,
            {
                setEditingComment: (_, { comment }) => comment,
                persistEditedCommentSuccess: () => null,
            },
        ],
        editingCommentRichContentEditor: [
            null as RichContentEditorType | null,
            {
                setEditingCommentRichContentEditor: (_, { editor }) => editor,
                persistEditedCommentSuccess: () => null,
            },
        ],
        editingCommentExistingMentions: [
            null as number[] | null,
            {
                setEditingCommentRichContentEditor: (_, { editor }) => editor?.getMentions() ?? [],
                persistEditedCommentSuccess: () => null,
            },
        ],
        isEditingCommentEmpty: [
            false as boolean,
            {
                onEditingCommentRichContentEditorUpdate: (_, { isEmpty }) => isEmpty,
                persistEditedCommentSuccess: () => false,
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

                    const mentions = values.richContentEditor?.getMentions() ?? []

                    const newComment = await api.comments.create({
                        rich_content: values.richContentEditor?.getJSON(),
                        scope: props.scope,
                        item_id: props.item_id,
                        item_context: itemContext,
                        source_comment: values.replyingCommentId ?? undefined,
                        mentions,
                    })

                    values.itemContext?.callback?.({ sent: true })
                    return [...existingComments, newComment]
                },

                persistEditedComment: async () => {
                    const existingComments = values.comments ?? []
                    const editedComment = values.editingComment

                    if (!editedComment) {
                        return existingComments
                    }

                    const originalComment = existingComments.find((c) => c.id === editedComment.id)

                    if (!originalComment) {
                        return existingComments
                    }

                    const previousMentions = values.editingCommentExistingMentions ?? []
                    const currentMentions = values.editingCommentRichContentEditor?.getMentions() ?? []
                    const newMentions = currentMentions.filter((m) => !previousMentions.includes(m))

                    const { id, rich_content } = editedComment

                    const updatedComment = await api.comments.update(id, {
                        rich_content,
                        content: null,
                        new_mentions: newMentions,
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
                        mentions: [],
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
                values.richContentEditor?.focus()
            }
        },
        focusComposer: () => {
            values.richContentEditor?.focus()
        },
        maybeLoadComments: () => {
            if (!values.comments && !values.commentsLoading) {
                actions.loadComments()
            }
        },
        sendComposedContentSuccess: () => {
            actions.incrementCommentCount()
            values.richContentEditor?.clear()
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
                        // TODO: emoji reactions still use the content field for now
                        const emoji = comment.content!
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
