import { OrganizationMembershipLevel } from 'lib/constants'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { OrganizationType, TeamType } from '~/types'

export function canUseCrossProjectQuerying(
    currentTeam:
        | Pick<TeamType, 'can_query_across_organization_projects' | 'effective_membership_level'>
        | null
        | undefined,
    currentOrganization: Pick<OrganizationType, 'membership_level' | 'teams'> | null | undefined
): boolean {
    const hasOrgAdminAccess =
        (currentTeam?.effective_membership_level ?? null) !== null
            ? (currentTeam?.effective_membership_level ?? 0) >= OrganizationMembershipLevel.Admin
            : (currentOrganization?.membership_level ?? 0) >= OrganizationMembershipLevel.Admin

    const hasMultipleProjects = currentOrganization?.teams ? currentOrganization.teams.length > 1 : true

    return Boolean(currentTeam?.can_query_across_organization_projects && hasOrgAdminAccess && hasMultipleProjects)
}

export function areAllOrganizationTeamsSelected(modifiers?: HogQLQueryModifiers | null): boolean {
    return modifiers?.teamsToQuery === 'all'
}
