import { TeamPublicType, TeamType, UserType } from '~/types'

export function hasPendingDelegationForCurrentOrg(user: UserType | null | undefined): boolean {
    return Boolean(
        user?.onboarding_delegated_to_invite &&
        !user?.onboarding_delegation_accepted_at &&
        user?.onboarding_delegated_to_organization_id &&
        user.onboarding_delegated_to_organization_id === user.organization?.id
    )
}

function hasSkippedForCurrentOrg(user: UserType | null | undefined): boolean {
    // Skip state is org-scoped: a user who skips onboarding in Org A should still see
    // onboarding when they switch to or create Org B. The legacy null-org case (rows from
    // before onboarding_skipped_organization_id existed) is treated as a global skip so we
    // don't re-redirect users who already opted out of onboarding before this field shipped.
    if (!user?.onboarding_skipped_at) {
        return false
    }
    if (!user.onboarding_skipped_organization_id) {
        return true
    }
    return user.onboarding_skipped_organization_id === user.organization?.id
}

export function isOnboardingRedirectSuppressed(user: UserType | null | undefined): boolean {
    // Note: we deliberately do NOT suppress just because the user is an invitee
    // (`is_organization_first_user === false`). Invitees of an established org are already
    // protected from the redirect by `hasOnboardedAnyProduct` in sceneLogic. Invitees of a
    // fresh org are most likely delegates whose entire purpose is to *finish* onboarding —
    // suppressing for them would defeat the delegation feature.
    return hasSkippedForCurrentOrg(user) || hasPendingDelegationForCurrentOrg(user)
}

/**
 * Whether this team is in the "must complete onboarding first" state — the non-path-specific
 * half of the gate `sceneLogic` uses to redirect to `/onboarding`. Shared with the sidebar so it
 * can stop advertising destinations the gate would immediately bounce the user out of; combine
 * with a path check (`isOnboardingNotRequiredForPath` in `scenes/sceneLogic`) for the full gate.
 */
export function isOnboardingRequiredForTeam(
    user: UserType | null | undefined,
    team: TeamPublicType | TeamType | null | undefined,
    hasOnboardedAnyProduct: boolean
): boolean {
    return Boolean(
        team &&
        !team.is_demo &&
        user?.organization?.teams.length === 1 &&
        !hasOnboardedAnyProduct &&
        !team.ingested_event &&
        !isOnboardingRedirectSuppressed(user)
    )
}
