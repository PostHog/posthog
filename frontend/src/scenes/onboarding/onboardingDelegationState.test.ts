import { hasPendingDelegationForCurrentOrg } from 'scenes/onboarding/onboardingDelegationState'

describe('hasPendingDelegationForCurrentOrg', () => {
    it('returns true for pending delegation in current org', () => {
        expect(
            hasPendingDelegationForCurrentOrg({
                onboarding_delegated_to_invite: 'invite-1',
                onboarding_delegation_accepted_at: null,
                onboarding_delegated_to_organization_id: 'org-1',
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(true)
    })

    it('returns false when accepted timestamp is set', () => {
        expect(
            hasPendingDelegationForCurrentOrg({
                onboarding_delegated_to_invite: 'invite-1',
                onboarding_delegation_accepted_at: '2026-04-22T00:00:00Z',
                onboarding_delegated_to_organization_id: 'org-1',
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(false)
    })

    it('returns false for delegation in another organization', () => {
        expect(
            hasPendingDelegationForCurrentOrg({
                onboarding_delegated_to_invite: 'invite-1',
                onboarding_delegation_accepted_at: null,
                onboarding_delegated_to_organization_id: 'org-a',
                organization: { id: 'org-b' },
            } as any)
        ).toEqual(false)
    })
})
