import { useValues } from 'kea'

import { IconSupport } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'

import { supportTicketCounterLogic } from '../../supportTicketCounterLogic'

export interface SupportNavBadgeProps {
    className?: string
}

export function SupportNavBadge({ className }: SupportNavBadgeProps): JSX.Element {
    const { unreadCount } = useValues(supportTicketCounterLogic)

    return (
        <IconWithCount count={unreadCount} showZero={false} className={className}>
            <IconSupport />
        </IconWithCount>
    )
}
