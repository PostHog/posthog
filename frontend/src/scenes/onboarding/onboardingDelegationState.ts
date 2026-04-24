import { UserType } from '~/types'

export function hasPendingDelegationForCurrentOrg(user: UserType | null | undefined): boolean {
    return Boolean(
        user?.onboarding_delegated_to_invite &&
        !user?.onboarding_delegation_accepted_at &&
        user?.onboarding_delegated_to_organization_id &&
        user.onboarding_delegated_to_organization_id === user.organization?.id
    )
}

export function isOnboardingRedirectSuppressed(user: UserType | null | undefined): boolean {
    return Boolean(user?.onboarding_skipped_at || hasPendingDelegationForCurrentOrg(user))
}
