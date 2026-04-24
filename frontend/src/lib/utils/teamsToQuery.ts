import { OrganizationMembershipLevel } from 'lib/constants'
import { getAppContext } from 'lib/utils/getAppContext'

import { HogQLQueryModifiers } from '~/queries/schema/schema-general'
import { OrganizationType, TeamType } from '~/types'

export function canUseCrossProjectQuerying(
    currentTeam: Pick<TeamType, 'can_query_across_organization_projects'> | null | undefined,
    currentOrganization: Pick<OrganizationType, 'membership_level' | 'teams'> | null | undefined
): boolean {
    const contextualMembershipLevel = getAppContext()?.current_user?.organization?.membership_level
    const membershipLevel = currentOrganization?.membership_level ?? contextualMembershipLevel ?? 0

    return Boolean(
        currentTeam?.can_query_across_organization_projects && membershipLevel >= OrganizationMembershipLevel.Admin
    )
}

export function areAllOrganizationTeamsSelected(modifiers?: HogQLQueryModifiers | null): boolean {
    return modifiers?.teamsToQuery === 'all'
}
