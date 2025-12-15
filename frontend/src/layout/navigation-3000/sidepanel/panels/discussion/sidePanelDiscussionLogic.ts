import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { CommentsLogicProps } from 'scenes/comments/commentsLogic'

import { sidePanelContextLogic } from '../sidePanelContextLogic'
import type { sidePanelDiscussionLogicType } from './sidePanelDiscussionLogicType'

export const sidePanelDiscussionLogic = kea<sidePanelDiscussionLogicType>([
    path(['scenes', 'navigation', 'sidepanel', 'sidePanelDiscussionLogic']),
    actions({
        loadCommentCount: true,
        resetCommentCount: true,
        scrollToLastComment: true,
        setCommentsListRef: (ref: HTMLDivElement) => ({ ref }),
    }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags'], sidePanelContextLogic, ['sceneSidePanelContext']],
    })),
    reducers({
        commentsListRef: [
            null as HTMLDivElement | null,
            {
                setCommentsListRef: (_, { ref }) => ref,
            },
        ],
    }),
    loaders(({ values }) => ({
        commentCount: [
            0,
            {
                loadCommentCount: async (_, breakpoint) => {
                    if (!values.commentsLogicProps || values.commentsLogicProps.disabled) {
                        return 0
                    }

                    await breakpoint(100)
                    const response = await api.comments.getCount({
                        ...values.commentsLogicProps,
                        exclude_emoji_reactions: true,
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
    listeners(({ values }) => ({
        scrollToLastComment() {
            const commentsListRef = values.commentsListRef
            if (commentsListRef) {
                setTimeout(() => {
                    commentsListRef.scrollTop = commentsListRef.scrollHeight
                }, 100)
            }
        },
    })),
    selectors({
        commentsLogicProps: [
            (s) => [s.sceneSidePanelContext],
            (sceneSidePanelContext): CommentsLogicProps | null => {
                return sceneSidePanelContext.activity_scope
                    ? {
                          scope: sceneSidePanelContext.activity_scope,
                          item_id: sceneSidePanelContext.activity_item_id,
                          item_context: sceneSidePanelContext.activity_item_context,
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
