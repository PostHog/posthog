import { actions, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

import type { sidePanelDiscussionLogicType } from './sidePanelDiscussionLogicType'

export const urlToCommentsLogicProps = (path: string): CommentsLogicProps => {
    return {
        scope: 'Misc',
        item_id: path,
    }
}

export const sidePanelDiscussionLogic = kea<sidePanelDiscussionLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDiscussionLogic']),
    actions({
        loadCommentCount: true,
    }),
    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    await breakpoint(100)
                    const response = await api.comments.getCount({
                        ...values.commentsLogicProps,
                    })

                    breakpoint()

                    return response
                },
            },
        ],
    })),

    selectors({
        commentsLogicProps: [
            () => [router.selectors.location],
            (location): CommentsLogicProps => {
                return urlToCommentsLogicProps(location.pathname)
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        commentsLogicProps: () => {
            actions.loadCommentCount()
        },
    })),
])
