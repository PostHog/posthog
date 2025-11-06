import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { ZendeskTicket } from '~/types'

import { sidePanelTicketsLogic } from './sidePanelTicketsLogic'
import { TicketCard } from './tickets/TicketCard'

export function SidePanelTickets(): JSX.Element {
    const logic = sidePanelTicketsLogic({ key: 'sidebar' })
    const { tickets, ticketsResponseLoading, hasError } = useValues(logic)
    const { loadTickets } = useActions(logic)

    return (
        <BindLogic logic={sidePanelTicketsLogic} props={{ key: 'sidebar' }}>
            <div className="flex flex-col p-3">
                <div>
                    {ticketsResponseLoading && tickets.length === 0 ? (
                        <div className="flex items-center justify-center h-32">
                            <Spinner />
                        </div>
                    ) : hasError ? (
                        <div className="text-center p-8">
                            <p className="text-muted mb-4">Failed to load tickets</p>
                            <LemonButton type="secondary" onClick={() => loadTickets()}>
                                Try again
                            </LemonButton>
                        </div>
                    ) : tickets.length === 0 ? (
                        <div className="text-center p-8">
                            <p className="text-muted mb-2">No open tickets</p>
                            <p className="text-xs text-muted">
                                Your support tickets will appear here once you create them
                            </p>
                        </div>
                    ) : (
                        <div>
                            {tickets.map((ticket: ZendeskTicket) => (
                                <TicketCard key={ticket.id} ticket={ticket} />
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </BindLogic>
    )
}
