import { useActions, useValues } from 'kea'

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
import { TicketSidebarWidgetSlots } from '../TicketSidebarWidgets/ticketSidebarLayout'
import { TicketSidebarWidgets } from '../TicketSidebarWidgets/TicketSidebarWidgets'

const WIDGET_TICKET_ONLY = 'Only shows on tickets from the in-app widget.'

export function SupportTicketSidebarWidgets({ ticketId }: { ticketId: string }): JSX.Element {
    const { ticket, person, eventsQuery, exceptionsQuery, previousTickets, previousTicketsLoading, aiRerunning } =
        useValues(supportTicketSceneLogic({ id: ticketId }))
    const { rerunAi } = useActions(supportTicketSceneLogic({ id: ticketId }))
    const { user } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const aiSuggestionsEnabled = !!currentTeam?.conversations_settings?.ai_suggestions_enabled
    const isWidgetTicket = ticket?.channel_source === 'widget'

    const personUuid = person?.uuid ?? ticket?.person?.id

    const slots: TicketSidebarWidgetSlots = {
        related_groups: {
            content:
                personUuid || ticket?.organization_id ? (
                    <RelatedGroupsPanel
                        personUuid={personUuid}
                        organizationId={ticket?.organization_id}
                        organizationIdSource={ticket?.organization_id_source}
                    />
                ) : null,
            unavailableReason: 'This ticket has no linked person or organization.',
        },
        ...(user?.is_staff ? { staff_actions: { content: ticket ? <StaffActionsPanel /> : null } } : {}),
        ai_triage: {
            content:
                aiSuggestionsEnabled && ticket ? (
                    <AIPanel aiTriage={ticket.ai_triage} onRerun={rerunAi} rerunning={aiRerunning} />
                ) : null,
            unavailableReason: 'AI suggestions are off for this project.',
        },
        session_recording: {
            content: isWidgetTicket ? (
                <SessionRecordingPanel sessionContext={ticket?.session_context} distinctId={ticket?.distinct_id} />
            ) : null,
            unavailableReason: WIDGET_TICKET_ONLY,
        },
        recent_events: {
            content: isWidgetTicket ? (
                <RecentEventsPanel
                    eventsQuery={eventsQuery}
                    distinctId={ticket?.distinct_id}
                    sessionId={ticket?.session_id}
                />
            ) : null,
            unavailableReason: WIDGET_TICKET_ONLY,
        },
        exceptions: {
            content: isWidgetTicket ? (
                <ExceptionsPanel
                    exceptionsQuery={exceptionsQuery}
                    sessionId={ticket?.session_id}
                    distinctId={ticket?.distinct_id}
                />
            ) : null,
            unavailableReason: WIDGET_TICKET_ONLY,
        },
        previous_tickets: {
            content: isWidgetTicket ? (
                <PreviousTicketsPanel
                    previousTickets={previousTickets}
                    previousTicketsLoading={previousTicketsLoading}
                    personDistinctIds={person?.distinct_ids}
                />
            ) : null,
            unavailableReason: WIDGET_TICKET_ONLY,
        },
        activity: {
            content: ticket?.id ? <TicketActivityPanel ticketId={ticket.id} /> : null,
        },
    }

    return <TicketSidebarWidgets slots={slots} />
}
