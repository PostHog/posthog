import { fullName, humanList } from 'lib/utils/strings'

import type { UserBasicApi } from '../../generated/api.schemas'

export type TicketViewer = Pick<UserBasicApi, 'id' | 'email' | 'first_name' | 'last_name'>

export function viewerDisplayName(viewer: TicketViewer): string {
    return fullName(viewer) || viewer.email
}

export function ticketViewersTooltip(viewers: TicketViewer[], { also = false }: { also?: boolean } = {}): string {
    const names = humanList(viewers.map(viewerDisplayName))
    const verb = viewers.length === 1 ? 'is' : 'are'
    return `${names} ${verb} ${also ? 'also ' : ''}viewing this ticket`
}
