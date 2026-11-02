export type TicketSidebarCardRowId =
    | 'customer'
    | 'created'
    | 'updated'
    | 'channel'
    | 'page_url'
    | 'status'
    | 'priority'
    | 'assignee'
    | 'sla'
    | 'snooze'
    | 'tags'
    | 'delete'

export interface SidebarCardRowConfig {
    id: TicketSidebarCardRowId
    visible: boolean
}

export type SidebarCardLayout = SidebarCardRowConfig[]

export interface SidebarRowMeta {
    id: TicketSidebarCardRowId
    label: string
    description: string
}

export const SIDEBAR_ROW_META: Record<TicketSidebarCardRowId, SidebarRowMeta> = {
    customer: {
        id: 'customer',
        label: 'Customer',
        description: 'Customer contact details, email shortcut, and verification status',
    },
    created: {
        id: 'created',
        label: 'Created',
        description: 'Date and time the ticket was initially opened',
    },
    updated: {
        id: 'updated',
        label: 'Updated',
        description: 'Date and time of the most recent message or activity',
    },
    channel: {
        id: 'channel',
        label: 'Channel',
        description: 'Inbound channel source, email headers, and external links',
    },
    page_url: {
        id: 'page_url',
        label: 'Page URL',
        description: 'Active URL where the user submitted the conversation or report',
    },
    status: {
        id: 'status',
        label: 'Status',
        description: 'Current ticket lifecycle state (open, pending, on hold, resolved)',
    },
    priority: {
        id: 'priority',
        label: 'Priority',
        description: 'Severity level (low, medium, high, urgent)',
    },
    assignee: {
        id: 'assignee',
        label: 'Assignee',
        description: 'Owner agent or team assignment',
    },
    sla: {
        id: 'sla',
        label: 'SLA',
        description: 'Service level agreement countdown and target response time',
    },
    snooze: {
        id: 'snooze',
        label: 'Snooze',
        description: 'Temporarily hide or hold the ticket until a future time',
    },
    tags: {
        id: 'tags',
        label: 'Tags',
        description: 'Labels for categorization, routing, and reporting',
    },
    delete: {
        id: 'delete',
        label: 'Delete button',
        description: 'Option to permanently remove the ticket in the card footer',
    },
}

export const DEFAULT_SIDEBAR_CARD_LAYOUT: SidebarCardLayout = [
    { id: 'customer', visible: true },
    { id: 'created', visible: true },
    { id: 'updated', visible: true },
    { id: 'channel', visible: true },
    { id: 'page_url', visible: true },
    { id: 'status', visible: true },
    { id: 'priority', visible: true },
    { id: 'assignee', visible: true },
    { id: 'sla', visible: true },
    { id: 'snooze', visible: true },
    { id: 'tags', visible: true },
    { id: 'delete', visible: true },
]

export const ALL_ROW_IDS = DEFAULT_SIDEBAR_CARD_LAYOUT.map((row) => row.id)

/**
 * Validates and normalizes an unknown layout representation from localStorage
 * or team conversations_settings into a strict SidebarCardLayout.
 * Missing rows are appended at the end with their default visibility.
 * Invalid row IDs are discarded.
 */
export function normalizeSidebarLayout(raw: unknown): SidebarCardLayout {
    if (!Array.isArray(raw)) {
        return [...DEFAULT_SIDEBAR_CARD_LAYOUT]
    }

    const seenIds = new Set<TicketSidebarCardRowId>()
    const normalized: SidebarCardLayout = []

    for (const item of raw) {
        if (!item || typeof item !== 'object') {
            continue
        }
        const id = (item as any).id as TicketSidebarCardRowId
        if (ALL_ROW_IDS.includes(id) && !seenIds.has(id)) {
            seenIds.add(id)
            normalized.push({
                id,
                visible: typeof (item as any).visible === 'boolean' ? (item as any).visible : true,
            })
        }
    }

    // Append any default rows not present in the stored layout
    for (const defaultRow of DEFAULT_SIDEBAR_CARD_LAYOUT) {
        if (!seenIds.has(defaultRow.id)) {
            normalized.push({ ...defaultRow })
        }
    }

    return normalized
}

export function moveSidebarRow(layout: SidebarCardLayout, fromIndex: number, toIndex: number): SidebarCardLayout {
    if (fromIndex < 0 || fromIndex >= layout.length || toIndex < 0 || toIndex >= layout.length || fromIndex === toIndex) {
        return layout
    }
    const next = [...layout]
    const [moved] = next.splice(fromIndex, 1)
    next.splice(toIndex, 0, moved)
    return next
}

export function toggleSidebarRow(layout: SidebarCardLayout, rowId: TicketSidebarCardRowId): SidebarCardLayout {
    return layout.map((row) => (row.id === rowId ? { ...row, visible: !row.visible } : row))
}
