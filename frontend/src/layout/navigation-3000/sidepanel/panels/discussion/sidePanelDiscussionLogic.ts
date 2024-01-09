import { actions, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

import { activityForSceneLogic } from '../activity/activityForSceneLogic'
import type { sidePanelDiscussionLogicType } from './sidePanelDiscussionLogicType'

export const sidePanelDiscussionLogic = kea<sidePanelDiscussionLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDiscussionLogic']),
    actions({
        loadCommentCount: true,
    }),
    connect({
        values: [featureFlagLogic, ['featureFlags'], activityForSceneLogic, ['sceneActivityFilters']],
    }),
    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    if (!values.featureFlags[FEATURE_FLAGS.DISCUSSIONS] || !values.commentsLogicProps) {
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
            (s) => [s.sceneActivityFilters],
            (activityFilters): CommentsLogicProps | null => {
                return activityFilters?.scope
                    ? {
                          scope: activityFilters.scope,
                          item_id: activityFilters.item_id,
                      }
                    : null
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        commentsLogicProps: (props) => {
            if (props) {
                actions.loadCommentCount()
            }
        },
    })),
])
