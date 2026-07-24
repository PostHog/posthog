import type { OrganizationMemberType, RoleType } from '~/types'

export type TicketAssignee = {
    type: 'user' | 'role'
    id: string | number
} | null

// `'me'` is a dynamic, per-viewer token: it filters to whoever is currently
// signed in, resolved server-side against `request.user`. Unlike a concrete
// `{ type: 'user', id }` entry it stays correct when a saved view is shared, so
// a "My tickets" view means each teammate's own tickets rather than the
// creator's. It's a filter-only concept — a ticket's actual assignee is always
// a concrete user/role, never `'me'`.
export type AssigneeFilterEntry = 'unassigned' | 'me' | NonNullable<TicketAssignee>

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
