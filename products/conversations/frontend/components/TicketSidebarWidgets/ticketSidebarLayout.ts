import { TicketSidebarConfiguration } from '~/queries/schema/schema-general'

// pinned: widget keys are stored in each user's saved layout on their account. Renaming one resets it.
export type TicketSidebarWidgetKey =
    | 'related_groups'
    | 'staff_actions'
    | 'ai_triage'
    | 'session_recording'
    | 'recent_events'
    | 'exceptions'
    | 'previous_tickets'
    | 'activity'

export interface TicketSidebarWidgetDefinition {
    key: TicketSidebarWidgetKey
    title: string
    description: string
}

/** The order here is the default layout, and where a widget lands when a saved layout predates it. */
export const TICKET_SIDEBAR_WIDGETS: TicketSidebarWidgetDefinition[] = [
    {
        key: 'related_groups',
        title: 'Related groups',
        description: 'Groups the customer belongs to, with revenue.',
    },
    {
        key: 'staff_actions',
        title: 'Staff actions',
        description: 'Log in as the customer. Only visible to staff.',
    },
    {
        key: 'ai_triage',
        title: 'AI triage',
        description: 'What the AI found when it triaged the ticket.',
    },
    {
        key: 'session_recording',
        title: 'Session recording',
        description: 'The recording of the session the ticket came from.',
    },
    {
        key: 'recent_events',
        title: 'Recent events',
        description: 'Events from around the time the ticket was created.',
    },
    {
        key: 'exceptions',
        title: 'Exceptions',
        description: 'Exceptions from the session the ticket came from.',
    },
    {
        key: 'previous_tickets',
        title: 'Previous tickets',
        description: 'Other tickets from the same customer.',
    },
    {
        key: 'activity',
        title: 'Ticket activity history',
        description: 'Changes made to this ticket.',
    },
]

const WIDGETS_BY_KEY = new Map(TICKET_SIDEBAR_WIDGETS.map((widget) => [widget.key, widget]))

export function ticketSidebarWidget(key: TicketSidebarWidgetKey): TicketSidebarWidgetDefinition {
    return WIDGETS_BY_KEY.get(key) as TicketSidebarWidgetDefinition
}

function isTicketSidebarWidgetKey(key: unknown): key is TicketSidebarWidgetKey {
    return typeof key === 'string' && WIDGETS_BY_KEY.has(key as TicketSidebarWidgetKey)
}

export interface TicketSidebarLayout {
    visible: TicketSidebarWidgetKey[]
    hidden: TicketSidebarWidgetKey[]
}

export function resolveTicketSidebarLayout(stored: TicketSidebarConfiguration | null | undefined): TicketSidebarLayout {
    const order = Array.from(new Set((stored?.order ?? []).filter(isTicketSidebarWidgetKey)))
    // A widget added after the layout was saved shows up instead of staying hidden forever.
    for (const { key } of TICKET_SIDEBAR_WIDGETS) {
        if (!order.includes(key)) {
            order.push(key)
        }
    }
    const hidden = new Set((stored?.hidden ?? []).filter(isTicketSidebarWidgetKey))
    return {
        visible: order.filter((key) => !hidden.has(key)),
        hidden: order.filter((key) => hidden.has(key)),
    }
}

export const DEFAULT_TICKET_SIDEBAR_LAYOUT: TicketSidebarLayout = resolveTicketSidebarLayout(null)

export function storeTicketSidebarLayout(layout: TicketSidebarLayout): Required<TicketSidebarConfiguration> {
    return { order: [...layout.visible, ...layout.hidden], hidden: [...layout.hidden] }
}

export function ticketSidebarLayoutsEqual(a: TicketSidebarLayout, b: TicketSidebarLayout): boolean {
    return a.visible.join() === b.visible.join() && a.hidden.join() === b.hidden.join()
}

export interface TicketSidebarWidgetSlot {
    /** null when the widget has nothing to show on this ticket. */
    content: JSX.Element | null
    unavailableReason?: string
}

/** A widget the current user may not see (such as staff actions) has no slot, so the editor leaves it out too. */
export type TicketSidebarWidgetSlots = Partial<Record<TicketSidebarWidgetKey, TicketSidebarWidgetSlot>>
