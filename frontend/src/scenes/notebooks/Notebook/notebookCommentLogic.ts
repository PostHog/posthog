import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'

import { CommentType } from '~/types'

import type { notebookCommentLogicType } from './notebookCommentLogicType'
import { notebookLogic } from './notebookLogic'

export const notebookCommentLogic = kea<notebookCommentLogicType>([
    path(() => ['scenes', 'notebooks', 'Notebook', 'notebookCommentLogic']),
    connect(() => ({
        values: [notebookLogic, ['editor']],
    })),
    actions({
        setIsShowingComments: (isShowingComments: boolean) => ({ isShowingComments }),
        setIsEditingComment: (isEditingComment: boolean) => ({ isEditingComment }),
        setCommentId: (commentId: string | null) => ({ commentId }),
        setLocalContent: (content: string) => ({ content }),
        cancelEditingComment: true,
    }),
    reducers(() => ({
        isShowingComments: [
            false,
            {
                setIsShowingComments: (_, { isShowingComments }) => isShowingComments,
            },
        ],
        isEditingComment: [
            false,
            {
                setIsEditingComment: (_, { isEditingComment }) => isEditingComment,
            },
        ],
        commentId: [
            null as string | null,
            {
                setCommentId: (_, { commentId }) => commentId,
            },
        ],
        localContent: [
            '' as string,
            {
                setLocalContent: (_, { content }) => content,
            },
        ],
    })),
    loaders(({ values }) => ({
        comment: [
            null as CommentType | null,
            {
                loadComment: async (commentId: string) => {
                    // Note: Does this need to be a network request or will we prefetch all notebook comments?
                    return await api.comments.get(commentId)
                },
                saveComment: async () => {
                    const comment = await api.comments.create({ content: values.localContent, scope: 'Notebook' })
                    values.editor?.chain().focus().setMark('comment', { id: comment.id }).run()
                    return comment
                },
            },
        ],
    })),
    subscriptions(({ actions }) => ({
        commentId: (commentId) => {
            if (commentId) {
                actions.loadComment(commentId)
            }
        },
    })),
    listeners(({ values, actions }) => ({
        loadComment: () => {
            if (values.comment) {
                actions.setLocalContent(values.comment.content)
            }
        },
        saveComment: () => {
            actions.setIsEditingComment(false)
        },
        cancelEditingComment: () => {
            actions.setLocalContent('')
            actions.setIsShowingComments(false)
        },
    })),
])
