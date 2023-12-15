import { IconChat } from '@posthog/icons'
import { useValues } from 'kea'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { CommentComposer } from 'scenes/comments/CommentComposer'
import { CommentsList } from 'scenes/comments/CommentsList'

import { SidePanelPaneHeader } from '../../components/SidePanelPaneHeader'
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
