import { IconChat } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { humanizeScope } from 'lib/components/ActivityLog/humanizeActivity'
import { WarningHog } from 'lib/components/hedgehogs'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'
import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'
import { commentsLogic, CommentsLogicProps } from 'scenes/comments/commentsLogic'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../../sidePanelStateLogic'
import { sidePanelDiscussionLogic } from './sidePanelDiscussionLogic'

export const SidePanelDiscussionIcon = (props: { className?: string }): JSX.Element => {
    const { commentCount } = useValues(sidePanelDiscussionLogic)

    return (
        <IconWithCount count={commentCount} {...props}>
            <IconChat />
        </IconWithCount>
    )
}

const DiscussionContent = ({ logicProps }: { logicProps: CommentsLogicProps }): JSX.Element => {
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const { setReplyingComment } = useActions(commentsLogic(logicProps))

    useEffect(() => {
        if (selectedTabOptions) {
            setReplyingComment(selectedTabOptions)
        }
    }, [selectedTabOptions])

    return (
        <div className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-2">
                <CommentsList {...logicProps} />
            </div>

            <div className="border-t px-3 pb-3">
                <CommentComposer {...logicProps} />
            </div>
        </div>
    )
}

export const SidePanelDiscussion = (): JSX.Element => {
    const { commentsLogicProps } = useValues(sidePanelDiscussionLogic)

    const { scope, item_id } = commentsLogicProps ?? {}

    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelPaneHeader
                title={
                    <>
                        Discussion{' '}
                        {scope ? (
                            <span className="font-normal text-muted-alt">
                                about {item_id ? 'this' : ''} {humanizeScope(scope, !!item_id)}
                            </span>
                        ) : null}
                    </>
                }
            />

            {commentsLogicProps ? (
                <DiscussionContent logicProps={commentsLogicProps} />
            ) : (
                <div className="mx-auto p-8 max-w-160 mt-8 space-y-4">
                    <div className="max-w-80 mx-auto">
                        <WarningHog className="w-full h-full" />
                    </div>
                    <h2>Discussions aren't supported here yet...</h2>
                    <p>
                        This a beta feature that is currently only available when viewing things like an Insight,
                        Dashboard or Notebook.
                    </p>
                </div>
            )}
        </div>
    )
}
