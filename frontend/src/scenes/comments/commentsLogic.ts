import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { CommentType } from '~/types'

import type { commentsLogicType } from './commentsLogicType'

export type CommentsLogicProps = {
    scope: CommentType['scope']
    item_id?: CommentType['item_id']
}

export type CommentWithRepliesType = {
    id: CommentType['id']
    comment?: CommentType // It may have been deleted
    replies: CommentType[]
}

export const commentsLogic = kea<commentsLogicType>([
    path(() => ['scenes', 'notebooks', 'Notebook', 'commentsLogic']),
    props({} as CommentsLogicProps),
    key((props) => `${props.scope}-${props.item_id || ''}`),

    // TODO: Connect to sidePanelDiscussionLogic and update the commentCount
    actions({
        loadComments: true,
        setComposedComment: (content: string) => ({ content }),
        sendComposedContent: true,
        deleteComment: (comment: CommentType) => ({ comment }),
        setEditingComment: (comment: CommentType | null) => ({ comment }),
        setReplyingComment: (commentId: string | null) => ({ commentId }),
        setItemContext: (context: Record<string, any> | null) => ({ context }),
        setCommentComposerBlurred: true,
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
                setCommentComposerBlurred: () => null,
            },
        ],
        itemContext: [
            null as Record<string, any> | null,
            {
                setItemContext: (_, { context }) => context,
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
                // TODO: This probably wants to be its own loader
                sendComposedContent: async () => {
                    const existingComments = values.comments ?? []
                    const newComment = await api.comments.create({
                        content: values.composedComment,
                        scope: props.scope,
                        item_id: props.item_id,
                        item_context: values.itemContext,
                        source_comment_id: values.replyingCommentId ?? undefined,
                    })
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
                        object: { name: 'Comment', id: comment.id },
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
            },
        ],
    })),

    listeners(({ values }) => ({
        focusComposer: () => {
            values.composerRef?.focus()
        },
    })),

    selectors({
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
                    let commentsWithReplies = commentsById[comment.source_comment_id ?? comment.id]

                    if (!commentsWithReplies) {
                        commentsById[comment.source_comment_id ?? comment.id] = commentsWithReplies = {
                            id: comment.source_comment_id ?? comment.id,
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
    }),

    subscriptions(({ actions }) => ({
        replyingCommentId: (value: string): void => {
            if (value) {
                actions.focusComposer()
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadComments()
    }),
])
