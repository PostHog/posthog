import { IconChat } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { useEffect } from 'react'
import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'
import { commentsLogic } from 'scenes/comments/commentsLogic'

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

export const SidePanelDiscussion = (): JSX.Element => {
    const { commentsLogicProps } = useValues(sidePanelDiscussionLogic)
    const { selectedTabOptions } = useValues(sidePanelStateLogic)
    const { setReplyingComment } = useActions(commentsLogic(commentsLogicProps))

    useEffect(() => {
        setReplyingComment(selectedTabOptions || null)
    }, [selectedTabOptions])

    return (
        <div className="flex flex-col overflow-hidden flex-1">
            <SidePanelPaneHeader title="Discussion" />

            <div className="flex flex-col flex-1 overflow-hidden">
                <div className="flex-1 overflow-y-auto p-2">
                    <CommentsList {...commentsLogicProps} />
                </div>

                <div className="border-t px-3 pb-3">
                    <CommentComposer {...commentsLogicProps} />
                </div>
            </div>
        </div>
    )
}
