import { TeamMembershipLevel } from 'lib/constants'

import { IntegrationKind } from '~/types'

// GitHub is the one project integration any member may connect, not just admins: the onboarding
// wizard runs as the current user and would otherwise abort for a non-admin on a project with no
// GitHub connection yet. Disconnecting/reconnecting and every other integration kind stay
// admin-only — both in this UI and again in the backend on IntegrationViewSet.
const MEMBER_CONNECTABLE_KINDS: ReadonlySet<IntegrationKind> = new Set<IntegrationKind>(['github'])

export function integrationConnectMinimumAccessLevel(kind: IntegrationKind): TeamMembershipLevel {
    return MEMBER_CONNECTABLE_KINDS.has(kind) ? TeamMembershipLevel.Member : TeamMembershipLevel.Admin
}
