import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import { posthog } from 'lib/posthog-typed'

import { AvailableFeature } from '~/types'

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

export interface RestrictedAreaCheck {
    /** Why the area is closed to this user, or null when they have access. Also null while the check loads. */
    restrictionReason: null | string
    /** True while the organization or project the check reads is still on its way. */
    isLoading: boolean
    /** Fetch the membership again, for a level that changed after this tab loaded. */
    revalidate: () => void
    isRevalidating: boolean
}

interface RestrictionStatus {
    loadingReason: null | string
    restrictionReason: null | string
}

function useRestrictionStatus({
    scope = RestrictionScope.Organization,
    minimumAccessLevel,
}: UseRestrictedAreaProps): RestrictionStatus {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    const status: RestrictionStatus = useMemo(() => {
        let scopeAccessLevel: EitherMembershipLevel | null
        if (scope === RestrictionScope.Project) {
            if (!isAuthenticatedTeam(currentTeam)) {
                return { loadingReason: 'Loading current project…', restrictionReason: null }
            }
            scopeAccessLevel = currentTeam.effective_membership_level
        } else {
            if (!currentOrganization) {
                return { loadingReason: 'Loading current organization…', restrictionReason: null }
            }
            scopeAccessLevel = currentOrganization.membership_level
        }

        if (scopeAccessLevel === null) {
            return { loadingReason: null, restrictionReason: `You don't have access to the current ${scope}.` }
        }

        if (scopeAccessLevel < minimumAccessLevel) {
            if (minimumAccessLevel === OrganizationMembershipLevel.Owner) {
                return { loadingReason: null, restrictionReason: `This area is restricted to the ${scope} owner.` }
            }
            return {
                loadingReason: null,
                restrictionReason: `This area is restricted to ${scope} ${membershipLevelToName.get(
                    minimumAccessLevel
                )}s and up. Your level is ${membershipLevelToName.get(scopeAccessLevel)}.`,
            }
        }
        return { loadingReason: null, restrictionReason: null }
    }, [currentOrganization, currentTeam, minimumAccessLevel]) // oxlint-disable-line react-hooks/exhaustive-deps

    const { restrictionReason } = status

    useEffect(() => {
        if (!restrictionReason || !currentTeam?.id || !currentOrganization?.id) {
            return
        }

        posthog.capture('restricted_area_accessed', {
            restriction_reason: restrictionReason,
            scope,
            minimum_access_level: minimumAccessLevel,
            team_id: currentTeam?.id,
            organization_id: currentOrganization?.id,
            platform_feature: AvailableFeature.ACCESS_CONTROL,
        })
    }, [restrictionReason, scope, minimumAccessLevel, currentTeam?.id, currentOrganization?.id])

    return status
}

/**
 * Same check as `useRestrictedArea`, with the loading state kept apart from the denial, and a way
 * to check the membership again. Use it where the restriction fills the whole surface.
 */
export function useRestrictedAreaCheck(props: UseRestrictedAreaProps): RestrictedAreaCheck {
    const { loadingReason, restrictionReason } = useRestrictionStatus(props)
    const { currentOrganizationLoading } = useValues(organizationLogic)
    const { loadCurrentOrganization } = useActions(organizationLogic)
    const { currentTeamLoading } = useValues(teamLogic)
    const { loadCurrentTeam } = useActions(teamLogic)

    const scope = props.scope ?? RestrictionScope.Organization
    const isProjectScope = scope === RestrictionScope.Project
    const isScopeLoading = isProjectScope ? currentTeamLoading : currentOrganizationLoading
    // A read that fails leaves the loader finished with nothing to check. Report that as a refusal
    // the retry can clear, because a spinner keyed on the missing value alone never stops.
    const isUnavailable = !!loadingReason && !isScopeLoading

    const revalidate = useCallback(() => {
        if (isProjectScope) {
            loadCurrentTeam()
        } else {
            loadCurrentOrganization()
        }
    }, [isProjectScope, loadCurrentTeam, loadCurrentOrganization])

    // The app seeds the membership level once at page load, so a level granted afterwards only
    // arrives on a reload. Read it back once when the user opens a surface this check gates,
    // whether the seeded level allows them in or not. Skip it while the read is unresolved,
    // because there is nothing to refresh and the retry covers a read that came back empty.
    const hasRevalidated = useRef(false)
    useEffect(() => {
        if (!loadingReason && !hasRevalidated.current) {
            hasRevalidated.current = true
            revalidate()
        }
    }, [loadingReason, revalidate])

    return {
        restrictionReason: isUnavailable ? `We couldn't check your access to the current ${scope}.` : restrictionReason,
        isLoading: !!loadingReason && !isUnavailable,
        revalidate,
        isRevalidating: isScopeLoading,
    }
}

export function useRestrictedArea(props: UseRestrictedAreaProps): null | string {
    const { loadingReason, restrictionReason } = useRestrictionStatus(props)
    return loadingReason ?? restrictionReason
}
