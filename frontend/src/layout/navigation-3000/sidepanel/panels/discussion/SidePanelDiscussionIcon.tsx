import { useValues } from 'kea'

import { IconChat } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'

import { sidePanelDiscussionLogic } from './sidePanelDiscussionLogic'

export const SidePanelDiscussionIcon = (props: { className?: string }): JSX.Element => {
    const { commentCount } = useValues(sidePanelDiscussionLogic)

    return (
        <IconWithCount count={commentCount} {...props}>
            <IconChat />
        </IconWithCount>
    )
}
