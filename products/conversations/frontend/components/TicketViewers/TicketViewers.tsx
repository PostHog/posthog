import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'

import { type TicketViewer, ticketViewersTooltip, viewerDisplayName } from './ticketPresence'

export interface TicketViewersProps {
    viewers: TicketViewer[]
    /** Bubbles shown before the "+n" overflow bubble. */
    limit?: number
    /** Phrase the tooltip as "also viewing", for a page the reader has open themselves. */
    also?: boolean
}

export function TicketViewers({ viewers, limit = 3, also = false }: TicketViewersProps): JSX.Element | null {
    if (viewers.length === 0) {
        return null
    }
    // The avatars are decorative (empty alt) and their names live only in the hover tooltip. Expose
    // the same sentence as the row's accessible name so screen-reader users can tell who is viewing.
    const label = ticketViewersTooltip(viewers, { also })
    return (
        <ProfileBubbles
            people={viewers.map((viewer) => ({ email: viewer.email, name: viewerDisplayName(viewer) }))}
            limit={limit}
            tooltip={label}
            role="img"
            aria-label={label}
        />
    )
}
