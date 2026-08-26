import { useValues } from 'kea'

import { ticketPresenceLogic } from './ticketPresenceLogic'
import { TicketViewers } from './TicketViewers'

export function TicketViewersCell({ ticketId }: { ticketId: string }): JSX.Element | null {
    const { viewersByTicketId } = useValues(ticketPresenceLogic)
    return <TicketViewers viewers={viewersByTicketId[ticketId] ?? []} />
}
