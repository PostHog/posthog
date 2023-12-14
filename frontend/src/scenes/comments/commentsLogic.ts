import { actions, afterMount, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

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
        loadCommentCount: true,
        setComposedComment: (content: string) => ({ content }),
        sendComposedContent: true,
    }),
    reducers({
        composedComment: [
            '',
            { persist: true },
            {
                setComposedComment: (_, { content }) => content,
                sendComposedContentSuccess: () => '',
            },
        ],
    }),
    loaders(({ props, values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async () => {
                    return await api.comments.getCount({
                        scope: props.scope,
                        item_id: props.item_id,
                    })
                },
            },
        ],
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
                    })
                    return [...existingComments, newComment]
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadCommentCount()
    }),
])
