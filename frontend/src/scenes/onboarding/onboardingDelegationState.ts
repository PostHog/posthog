import { UserType } from '~/types'

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
    // onboarding when they switch to or create Org B. Only suppress the redirect when
    // the recorded skip matches the current org.
    return Boolean(
        user?.onboarding_skipped_at &&
        user?.onboarding_skipped_organization_id &&
        user.onboarding_skipped_organization_id === user.organization?.id
    )
}

export function isOnboardingRedirectSuppressed(user: UserType | null | undefined): boolean {
    return hasSkippedForCurrentOrg(user) || hasPendingDelegationForCurrentOrg(user)
}
