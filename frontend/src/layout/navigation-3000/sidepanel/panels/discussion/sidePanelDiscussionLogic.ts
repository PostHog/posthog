import { actions, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'
import { routes, routesAsRegexes } from 'scenes/scenes'

import { ActivityScope } from '~/types'

import type { sidePanelDiscussionLogicType } from './sidePanelDiscussionLogicType'

const urlToCommentsLogicProps = (path: string, searchParams: Record<string, any>): CommentsLogicProps => {
    console.log(routesAsRegexes, path, searchParams)

    return {
        scope: ActivityScope.MISC,
        item_id: path,
    }
}

export const sidePanelDiscussionLogic = kea<sidePanelDiscussionLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDiscussionLogic']),
    actions({
        loadCommentCount: true,
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags']],
    }),
    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    if (!values.featureFlags[FEATURE_FLAGS.DISCUSSIONS]) {
                        return 0
                    }

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
            () => [router.selectors.currentLocation],
            (location): CommentsLogicProps => {
                return urlToCommentsLogicProps(location.pathname, location.searchParams)
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        commentsLogicProps: () => {
            actions.loadCommentCount()
        },
    })),
])
