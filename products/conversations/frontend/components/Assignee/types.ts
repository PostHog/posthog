import type { OrganizationMemberType, RoleType } from '~/types'

import type { TicketAssigneeRequestApi } from '../../generated/api.schemas'

export type TicketAssignee = TicketAssigneeRequestApi | null

// `'me'` is a dynamic, per-viewer token: it filters to whoever is currently
// signed in, resolved server-side against `request.user`. Unlike a concrete
// `{ type: 'user', id }` entry it stays correct when a saved view is shared, so
// a "My tickets" view means each teammate's own tickets rather than the
// creator's. It's a filter-only concept — a ticket's actual assignee is always
// a concrete user/role, never `'me'`.
export type AssigneeFilterEntry = 'unassigned' | 'me' | { type: 'user' | 'role'; id: string | number }

export function toTicketAssignee(entry: Exclude<AssigneeFilterEntry, string>): NonNullable<TicketAssignee> {
    return entry.type === 'user' ? { type: 'user', id: Number(entry.id) } : { type: 'role', id: String(entry.id) }
}

export function isSameAssigneeEntry(a: AssigneeFilterEntry, b: AssigneeFilterEntry): boolean {
    // String tokens ('unassigned', 'me') only match the identical token, never a concrete user/role.
    if (typeof a === 'string' || typeof b === 'string') {
        return a === b
    }
    return a.type === b.type && String(a.id) === String(b.id)
}

export function encodeAssigneeEntry(entry: AssigneeFilterEntry): string {
    // 'unassigned' and 'me' are string tokens; concrete entries encode as type:id.
    return typeof entry === 'string' ? entry : `${entry.type}:${entry.id}`
}

/** Reverses `encodeAssigneeEntry`. Returns null for a token that names no assignee. */
export function decodeAssigneeEntry(token: string): AssigneeFilterEntry | null {
    if (token === 'unassigned' || token === 'me') {
        return token
    }
    const separator = token.indexOf(':')
    const type = token.slice(0, separator)
    const id = token.slice(separator + 1)
    return (type === 'user' || type === 'role') && id ? { type, id } : null
}

/** Mirrors the entry cap the tickets list endpoint applies to the `assignee` param. */
export const MAX_ASSIGNEE_FILTER_ENTRIES = 100

export type UserAssignee = {
    id: number
    type: 'user'
    user: OrganizationMemberType['user']
}

export type RoleAssignee = {
    id: string
    type: 'role'
    role: RoleType
}

export type Assignee = UserAssignee | RoleAssignee | null
