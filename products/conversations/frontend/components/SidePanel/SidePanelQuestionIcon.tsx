import { useValues } from 'kea'

import { IconQuestion } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'

import { sidepanelTicketsLogic } from './sidepanelTicketsLogic'

export const SidePanelQuestionIcon = (props: { className?: string }): JSX.Element => {
    const { totalUnreadCount } = useValues(sidepanelTicketsLogic)
    return (
        <IconWithCount count={totalUnreadCount} {...props}>
            <IconQuestion />
        </IconWithCount>
    )
}
