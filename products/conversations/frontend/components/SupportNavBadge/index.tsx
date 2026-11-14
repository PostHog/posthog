import { useValues } from 'kea'

import { IconSupport } from '@posthog/icons'

import { IconWithCount } from 'lib/lemon-ui/icons'

import { supportTicketCounterLogic } from '../../supportTicketCounterLogic'

export interface SupportNavBadgeProps {
    className?: string
}

/** The unread ticket count. It mounts the counter logic, which polls only while Support is on. */
export function useSupportUnreadCount(): number {
    return useValues(supportTicketCounterLogic).unreadCount
}

export function SupportNavBadge({ className }: SupportNavBadgeProps): JSX.Element {
    const unreadCount = useSupportUnreadCount()

    return (
        <IconWithCount count={unreadCount} showZero={false} className={className}>
            <IconSupport />
        </IconWithCount>
    )
}
