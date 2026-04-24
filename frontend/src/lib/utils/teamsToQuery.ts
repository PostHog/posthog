import { OrganizationMembershipLevel } from 'lib/constants'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { OrganizationType, TeamType } from '~/types'

export function canUseCrossProjectQuerying(
    currentTeam: Pick<TeamType, 'can_query_across_organization_projects'> | null | undefined,
    currentOrganization: Pick<OrganizationType, 'membership_level' | 'teams'> | null | undefined
): boolean {
    return Boolean(
        currentTeam?.can_query_across_organization_projects &&
        currentOrganization?.membership_level &&
        currentOrganization.membership_level >= OrganizationMembershipLevel.Admin &&
        (currentOrganization.teams?.length ?? 0) > 1
    )
}

export function areAllOrganizationTeamsSelected(modifiers?: HogQLQueryModifiers | null): boolean {
    return modifiers?.teamsToQuery === 'all'
}
