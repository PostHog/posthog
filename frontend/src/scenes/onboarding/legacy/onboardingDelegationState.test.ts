import {
    hasPendingDelegationForCurrentOrg,
    isOnboardingRedirectSuppressed,
    isOnboardingRequiredForTeam,
} from 'scenes/onboarding/legacy/onboardingDelegationState'

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

describe('isOnboardingRedirectSuppressed', () => {
    it('suppresses when skip state matches the current org', () => {
        expect(
            isOnboardingRedirectSuppressed({
                onboarding_skipped_at: '2026-04-24T00:00:00Z',
                onboarding_skipped_organization_id: 'org-1',
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(true)
    })

    it('does NOT suppress when skip state was recorded for a different org', () => {
        expect(
            isOnboardingRedirectSuppressed({
                onboarding_skipped_at: '2026-04-24T00:00:00Z',
                onboarding_skipped_organization_id: 'org-other',
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(false)
    })

    it('suppresses legacy global skip (no org id) — these rows predate the org-scoped column', () => {
        expect(
            isOnboardingRedirectSuppressed({
                onboarding_skipped_at: '2026-04-24T00:00:00Z',
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(true)
    })

    it('suppresses when a pending delegation is attached to the current org', () => {
        expect(
            isOnboardingRedirectSuppressed({
                onboarding_delegated_to_invite: 'invite-1',
                onboarding_delegation_accepted_at: null,
                onboarding_delegated_to_organization_id: 'org-1',
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(true)
    })

    it('does NOT suppress for plain invitees — established orgs are already protected by hasOnboardedAnyProduct, fresh orgs are likely delegates', () => {
        expect(
            isOnboardingRedirectSuppressed({
                is_organization_first_user: false,
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(false)
    })

    it('does NOT suppress for org founders', () => {
        expect(
            isOnboardingRedirectSuppressed({
                is_organization_first_user: true,
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(false)
    })

    it('suppresses legacy null-org skip records (back-compat for users who skipped before onboarding_skipped_organization_id shipped)', () => {
        expect(
            isOnboardingRedirectSuppressed({
                onboarding_skipped_at: '2025-01-01T00:00:00Z',
                onboarding_skipped_organization_id: null,
                organization: { id: 'org-1' },
            } as any)
        ).toEqual(true)
    })
})

describe('isOnboardingRequiredForTeam', () => {
    const gatedUser = { organization: { id: 'org-1', teams: [{ id: 1 }] } } as any
    const gatedTeam = { is_demo: false, ingested_event: false } as any

    // Regression guard for the sidebar/scene gate extracted from sceneLogic's redirect condition:
    // any of these should turn a would-be redirect off, same as before the extraction.
    it.each<[string, Record<string, any>, Record<string, any>, boolean, boolean]>([
        ['baseline: single team, not demo, no event, not onboarded', {}, {}, false, true],
        ['demo team is exempt', {}, { is_demo: true }, false, false],
        [
            'org with more than one team is exempt',
            { organization: { id: 'org-1', teams: [{ id: 1 }, { id: 2 }] } },
            {},
            false,
            false,
        ],
        ['team has already ingested an event', {}, { ingested_event: true }, false, false],
        ['team has onboarded some product already', {}, {}, true, false],
        [
            'user has skipped onboarding for this org',
            { onboarding_skipped_at: '2026-04-24T00:00:00Z', onboarding_skipped_organization_id: 'org-1' },
            {},
            false,
            false,
        ],
    ])('%s', (_name, userOverrides, teamOverrides, hasOnboardedAnyProduct, expected) => {
        const user = {
            ...gatedUser,
            ...userOverrides,
            organization: { ...gatedUser.organization, ...userOverrides.organization },
        }
        const team = { ...gatedTeam, ...teamOverrides }
        expect(isOnboardingRequiredForTeam(user, team, hasOnboardedAnyProduct)).toEqual(expected)
    })

    it('is not required when there is no current team', () => {
        expect(isOnboardingRequiredForTeam(gatedUser, null, false)).toEqual(false)
    })
})
