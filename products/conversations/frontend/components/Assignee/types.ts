import type { OrganizationMemberType, RoleType } from '~/types'

export type TicketAssignee = {
    type: 'user' | 'role'
    id: string | number
} | null

export type AssigneeFilterEntry = 'unassigned' | NonNullable<TicketAssignee>

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
