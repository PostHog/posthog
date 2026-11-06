import { useValues } from 'kea'

import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { AIPanel } from '../../scenes/ticket/AIPanel'
import { ExceptionsPanel } from '../../scenes/ticket/ExceptionsPanel'
import { PreviousTicketsPanel } from '../../scenes/ticket/PreviousTicketsPanel'
import { RecentEventsPanel } from '../../scenes/ticket/RecentEventsPanel'
import { RelatedGroupsPanel } from '../../scenes/ticket/RelatedGroupsPanel'
import { SessionRecordingPanel } from '../../scenes/ticket/SessionRecordingPanel'
import { StaffActionsPanel } from '../../scenes/ticket/StaffActionsPanel'
import { supportTicketSceneLogic } from '../../scenes/ticket/supportTicketSceneLogic'
import { TicketActivityPanel } from '../../scenes/ticket/TicketActivityPanel'
import { TicketAiTracesPanel } from '../TicketAiTracesPanel/TicketAiTracesPanel'
import { TicketSidebarWidgetSlot, TicketSidebarWidgetSlots } from '../TicketSidebarWidgets/ticketSidebarLayout'
import { TicketSidebarWidgets } from '../TicketSidebarWidgets/TicketSidebarWidgets'

const WIDGET_TICKET_ONLY = 'Only shows on tickets from the in-app widget.'

function widgetTicketOnlySlot(isWidgetTicket: boolean, content: JSX.Element): TicketSidebarWidgetSlot {
    return { content: isWidgetTicket ? content : null, unavailableReason: WIDGET_TICKET_ONLY }
}

export function SupportTicketSidebarWidgets({ ticketId }: { ticketId: string }): JSX.Element {
    const { ticket, person, eventsQuery, exceptionsQuery, previousTickets, previousTicketsLoading } = useValues(
        supportTicketSceneLogic({ id: ticketId })
    )
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const aiSuggestionsEnabled = !!currentTeam?.conversations_settings?.ai_suggestions_enabled
    const isWidgetTicket = ticket?.channel_source === 'widget'

    const slots: TicketSidebarWidgetSlots = {
        related_groups: {
            content:
                person?.uuid || ticket?.organization_id ? (
                    <RelatedGroupsPanel
                        personUuid={person?.uuid}
                        organizationId={ticket?.organization_id}
                        organizationIdSource={ticket?.organization_id_source}
                    />
                ) : null,
            unavailableReason: 'This ticket has no linked person or organization.',
        },
        ...(user?.is_staff ? { staff_actions: { content: ticket ? <StaffActionsPanel /> : null } } : {}),
        ai_triage: {
            content: aiSuggestionsEnabled && ticket ? <AIPanel aiTriage={ticket.ai_triage} /> : null,
            unavailableReason: 'AI suggestions are off for this project.',
        },
        session_recording: widgetTicketOnlySlot(
            isWidgetTicket,
            <SessionRecordingPanel sessionContext={ticket?.session_context} distinctId={ticket?.distinct_id} />
        ),
        recent_events: widgetTicketOnlySlot(
            isWidgetTicket,
            <RecentEventsPanel
                eventsQuery={eventsQuery}
                distinctId={ticket?.distinct_id}
                sessionId={ticket?.session_id}
            />
        ),
        exceptions: widgetTicketOnlySlot(
            isWidgetTicket,
            <ExceptionsPanel
                exceptionsQuery={exceptionsQuery}
                sessionId={ticket?.session_id}
                distinctId={ticket?.distinct_id}
            />
        ),
        ai_traces: {
            content: person?.uuid ? <TicketAiTracesPanel personId={person.uuid} /> : null,
            unavailableReason: 'This ticket has no linked person.',
        },
        previous_tickets: widgetTicketOnlySlot(
            isWidgetTicket,
            <PreviousTicketsPanel
                previousTickets={previousTickets}
                previousTicketsLoading={previousTicketsLoading}
                personDistinctIds={person?.distinct_ids}
            />
        ),
        activity: {
            content: ticket?.id ? <TicketActivityPanel ticketId={ticket.id} /> : null,
        },
    }

    return <TicketSidebarWidgets slots={slots} />
}
