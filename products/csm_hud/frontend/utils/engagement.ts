import type { AccountActivity, NoteRow, TaskRow, TicketRow } from '../queries/activity'
import { daysUntil } from './format'

const OPEN_TICKET_STATUSES = new Set(['new', 'open', 'pending', 'hold'])

export interface ConversationsSummary {
    tickets: TicketRow[]
    openCount: number
    urgentCount: number
    latest: TicketRow | null
    oldestOpen: TicketRow | null
}

export function conversations(activity: AccountActivity | undefined): ConversationsSummary {
    const tickets = activity?.tickets ?? []
    const open = tickets.filter((t) => OPEN_TICKET_STATUSES.has(t.status.toLowerCase()))
    const urgent = open.filter((t) => (t.priority ?? '').toLowerCase() === 'urgent')
    const sortedByCreated = [...tickets].sort((x, y) => y.createdAt.localeCompare(x.createdAt))
    const oldestOpen = [...open].sort((x, y) => x.createdAt.localeCompare(y.createdAt))[0] ?? null
    return {
        tickets,
        openCount: open.length,
        urgentCount: urgent.length,
        latest: sortedByCreated[0] ?? null,
        oldestOpen,
    }
}

function maxIsoDate<T>(items: T[], pick: (item: T) => string | null): string | null {
    let max: string | null = null
    for (const it of items) {
        const v = pick(it)
        if (!v) {
            continue
        }
        if (!max || v > max) {
            max = v
        }
    }
    return max
}

export interface EngagementSummary {
    notes: NoteRow[]
    tasks: TaskRow[]
    lastNoteDate: string | null
    lastTaskDate: string | null
    lastTouchDate: string | null
    daysSinceLastTouch: number | null
}

export function engagement(activity: AccountActivity | undefined): EngagementSummary {
    const notes = activity?.notes ?? []
    const tasks = activity?.tasks ?? []
    const lastNoteDate = maxIsoDate(notes, (n) => n.noteDate)
    const lastTaskDate = maxIsoDate(
        tasks.filter((t) => t.completedAt != null),
        (t) => t.completedAt
    )
    const lastTouchDate =
        lastNoteDate && lastTaskDate
            ? lastNoteDate > lastTaskDate
                ? lastNoteDate
                : lastTaskDate
            : (lastNoteDate ?? lastTaskDate)
    // daysUntil returns negative for past dates; flip sign for "days since".
    const daysSince = daysUntil(lastTouchDate)
    return {
        notes,
        tasks,
        lastNoteDate,
        lastTaskDate,
        lastTouchDate,
        daysSinceLastTouch: daysSince == null ? null : -daysSince,
    }
}
