import { actions, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'
import { sceneLogic } from 'scenes/sceneLogic'

import { activityFiltersForScene } from '../activity/sidePanelActivityLogic'
import type { sidePanelDiscussionLogicType } from './sidePanelDiscussionLogicType'

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
            () => [sceneLogic.selectors.sceneConfig],
            (sceneConfig): CommentsLogicProps | null => {
                const context = activityFiltersForScene(sceneConfig)

                return context?.scope
                    ? {
                          scope: context.scope,
                          item_id: context.item_id,
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
