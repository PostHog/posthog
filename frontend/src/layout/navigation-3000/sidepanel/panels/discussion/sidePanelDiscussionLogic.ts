import { actions, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

import { sidePanelContextLogic } from '../sidePanelContextLogic'
import type { sidePanelDiscussionLogicType } from './sidePanelDiscussionLogicType'

export const sidePanelDiscussionLogic = kea<sidePanelDiscussionLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDiscussionLogic']),
    actions({
        loadCommentCount: true,
        resetCommentCount: true,
    }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], sidePanelContextLogic, ['sceneSidePanelContext']],
    })),
    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    if (
                        !values.featureFlags[FEATURE_FLAGS.DISCUSSIONS] ||
                        !values.commentsLogicProps ||
                        values.commentsLogicProps.disabled
                    ) {
                        return 0
                    }

                    await breakpoint(100)
                    const response = await api.comments.getCount({
                        ...values.commentsLogicProps,
                    })

                    breakpoint()

                    return response
                },
                incrementCommentCount: () => {
                    return values.commentCount + 1
                },
                resetCommentCount: () => {
                    return 0
                },
            },
        ],
    })),

    selectors({
        commentsLogicProps: [
            (s) => [s.sceneSidePanelContext],
            (sceneSidePanelContext): CommentsLogicProps | null => {
                return sceneSidePanelContext.activity_scope
                    ? {
                          scope: sceneSidePanelContext.activity_scope,
                          item_id: sceneSidePanelContext.activity_item_id,
                          disabled: sceneSidePanelContext.discussions_disabled,
                      }
                    : null
            },
        ],
    }),

    subscriptions(({ actions }) => ({
        commentsLogicProps: (props) => {
            if (props) {
                actions.loadCommentCount()
            } else {
                actions.resetCommentCount()
            }
        },
    })),
])
