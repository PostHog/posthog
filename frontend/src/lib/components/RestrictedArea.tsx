import { useValues } from 'kea'
import { useMemo } from 'react'

import { organizationLogic } from '../../scenes/organizationLogic'
import { isAuthenticatedTeam, teamLogic } from '../../scenes/teamLogic'
import { EitherMembershipLevel, OrganizationMembershipLevel } from '../constants'
import { membershipLevelToName } from '../utils/permissioning'

export interface RestrictedComponentProps {
    isRestricted: boolean
    restrictionReason: null | string
}

export enum RestrictionScope {
    /** Current organization-wide membership level will be used. */
    Organization = 'organization',
    /** Effective level for the current project will be used. */
    Project = 'project', // TODO: Rename, as this is actually the environment scope
}

export interface UseRestrictedAreaProps {
    minimumAccessLevel: EitherMembershipLevel
    scope?: RestrictionScope
}

export interface RestrictedAreaProps extends UseRestrictedAreaProps {
    Component: (props: RestrictedComponentProps) => JSX.Element
}

export function useRestrictedArea({
    scope = RestrictionScope.Organization,
    minimumAccessLevel,
}: UseRestrictedAreaProps): null | string {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const restrictionReason: null | string = useMemo(() => {
        let scopeAccessLevel: EitherMembershipLevel | null
        if (scope === RestrictionScope.Project) {
            if (!isAuthenticatedTeam(currentTeam)) {
                return 'Loading current project…'
            }
            scopeAccessLevel = currentTeam.effective_membership_level
        } else {
            if (!currentOrganization) {
                return 'Loading current organization…'
            }
            scopeAccessLevel = currentOrganization.membership_level
        }
        if (scopeAccessLevel === null) {
            return `You don't have access to the current ${scope}.`
        }
        if (scopeAccessLevel < minimumAccessLevel) {
            if (minimumAccessLevel === OrganizationMembershipLevel.Owner) {
                return `This area is restricted to the ${scope} owner.`
            }
            return `This area is restricted to ${scope} ${membershipLevelToName.get(
                minimumAccessLevel
            )}s and up. Your level is ${membershipLevelToName.get(scopeAccessLevel)}.`
        }
        return null
    }, [currentOrganization, currentTeam]) // oxlint-disable-line react-hooks/exhaustive-deps

    return restrictionReason
}
