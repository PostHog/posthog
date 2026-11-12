import { useValues } from 'kea'

import { IconChat } from '@posthog/icons'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@posthog/quill'

import { sidePanelDiscussionLogic } from '../sidePanelDiscussionLogic'
import { QuillDiscussion } from './QuillDiscussion'

export function QuillDiscussionPanel(): JSX.Element {
    const { commentsLogicProps, sceneSidePanelContext } = useValues(sidePanelDiscussionLogic)

    if (!commentsLogicProps || commentsLogicProps.disabled) {
        return (
            <Empty className="flex-1">
                <EmptyHeader>
                    <EmptyMedia variant="icon">
                        <IconChat />
                    </EmptyMedia>
                    <EmptyTitle>Discussions aren't available here</EmptyTitle>
                    <EmptyDescription>
                        {sceneSidePanelContext.discussions_disabled_reason ??
                            'Open an insight, a dashboard, or another saved object to discuss it with your team.'}
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return <QuillDiscussion logicProps={commentsLogicProps} />
}
