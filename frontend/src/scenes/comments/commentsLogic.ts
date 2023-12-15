import { actions, afterMount, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { CommentType } from '~/types'

import type { commentsLogicType } from './commentsLogicType'

export type CommentsLogicProps = {
    scope: CommentType['scope']
    item_id?: CommentType['item_id']
}

export const commentsLogic = kea<commentsLogicType>([
    path(() => ['scenes', 'notebooks', 'Notebook', 'notebookCommentLogic']),
    props({} as CommentsLogicProps),
    key((props) => `${props.scope}-${props.item_id || ''}`),
    actions({
        loadComments: true,
        setComposedComment: (content: string) => ({ content }),
        sendComposedContent: true,
        deleteComment: (comment: CommentType) => ({ comment }),
        setEditingComment: (comment: CommentType | null) => ({ comment }),
        setReplyingComment: (commentId: string | null) => ({ commentId }),
        persistEditedComment: true,
    }),
    reducers({
        replyingCommentId: [
            null as string | null,
            {
                setReplyingComment: (_, { commentId }) => commentId,
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

    selectors({
        sortedComments: [
            (s) => [s.comments],
            (comments) => {
                return comments?.sort((a, b) => (a.created_at > b.created_at ? 1 : -1)) ?? []
            },
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadComments()
    }),
])
