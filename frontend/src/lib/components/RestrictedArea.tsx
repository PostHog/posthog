import { useValues } from 'kea'
import React, { useMemo } from 'react'
import { organizationLogic } from '../../scenes/organizationLogic'
import { OrganizationMembershipLevel } from '../constants'
import { Tooltip } from 'lib/components/Tooltip'
import { EitherMembershipLevel, membershipLevelToName } from '../utils/permissioning'
import { teamLogic } from '../../scenes/teamLogic'

export interface RestrictedComponentProps {
    isRestricted: boolean
    restrictionReason: null | string
}

export enum RestrictionScope {
    /** Current organization-wide membership level will be used. */
    Organization = 'organization',
    /** Effective level for the current project will be used. */
    Project = 'project',
}

export interface RestrictedAreaProps {
    Component: (props: RestrictedComponentProps) => JSX.Element
    minimumAccessLevel: EitherMembershipLevel
    scope?: RestrictionScope
}

export function RestrictedArea({
    Component,
    minimumAccessLevel,
    scope = RestrictionScope.Organization,
}: RestrictedAreaProps): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const restrictionReason: null | string = useMemo(
        () => {
            let scopeAccessLevel: EitherMembershipLevel | null
            if (scope === RestrictionScope.Project) {
                if (!currentTeam) {
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
        },
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [currentOrganization]
    )

    return restrictionReason ? (
        <Tooltip title={restrictionReason} placement="topLeft" delayMs={0}>
            <span>
                <Component isRestricted={true} restrictionReason={restrictionReason} />
            </span>
        </Tooltip>
    ) : (
        <Component isRestricted={false} restrictionReason={null} />
    )
}
