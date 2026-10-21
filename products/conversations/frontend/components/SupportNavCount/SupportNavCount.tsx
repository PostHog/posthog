import { useValues } from 'kea'

import { Badge } from '@posthog/quill'

import { supportTicketCounterLogic } from '../../supportTicketCounterLogic'

export function SupportNavCount(): JSX.Element | null {
    const { unreadCount } = useValues(supportTicketCounterLogic)

    if (unreadCount <= 0) {
        return null
    }

    return (
        <Badge variant="destructive" className="tabular-nums" aria-label={`${unreadCount} unread tickets`}>
            {unreadCount > 99 ? '99+' : unreadCount}
        </Badge>
    )
}
