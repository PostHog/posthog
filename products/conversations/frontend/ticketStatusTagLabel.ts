import { type TicketStatus, sidePanelTicketFilterLabels, ticketStatusLabels } from './types'

export function ticketStatusTagLabel(
    status: TicketStatus | undefined,
    audience: 'team' | 'customer'
): string | undefined {
    if (status === 'on_hold' || status === 'escalated') {
        return audience === 'customer' ? sidePanelTicketFilterLabels[status] : ticketStatusLabels[status]
    }
    return status
}
