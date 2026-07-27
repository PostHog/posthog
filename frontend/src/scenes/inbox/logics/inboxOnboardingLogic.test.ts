import { computeOnboardingMode, InboxOnboardingMode, OnboardingModeInputs } from './inboxOnboardingLogic'

describe('computeOnboardingMode', () => {
    const base: OnboardingModeInputs = {
        isSetupLoaded: true,
        isSelfDrivingSetUp: false,
        areCountsResolved: true,
        hasExistingWork: false,
        bannerDismissed: false,
    }

    it.each<[string, Partial<OnboardingModeInputs>, InboxOnboardingMode]>([
        // Until the config check resolves, stay on the normal inbox (its own skeleton) – never guess
        // the takeover, which would jolt for a set-up user.
        ['config still loading', { isSetupLoaded: false }, 'none'],
        // Config not loaded wins even if the set-up flag is incidentally true – we don't trust it yet.
        ['config still loading, set-up flag ignored', { isSetupLoaded: false, isSelfDrivingSetUp: true }, 'none'],
        // Not set up, counts still loading → keep the inbox until we can choose takeover vs banner.
        ['not set up, counts still loading', { areCountsResolved: false }, 'none'],
        // Set up (a source or scout is watching) → no onboarding at all, and no wait on counts.
        ['set up, empty inbox', { isSelfDrivingSetUp: true }, 'none'],
        ['set up, with work', { isSelfDrivingSetUp: true, hasExistingWork: true }, 'none'],
        ['set up, counts unresolved (skipped)', { isSelfDrivingSetUp: true, areCountsResolved: false }, 'none'],
        // Not set up + nothing in the inbox → full-pane takeover (nothing to block).
        ['not set up, empty inbox', {}, 'takeover'],
        // Not set up but work exists → non-blocking banner, so existing work stays accessible.
        ['not set up, with work', { hasExistingWork: true }, 'banner'],
        // A dismissed banner falls back to the normal inbox for the session.
        ['not set up, with work, banner dismissed', { hasExistingWork: true, bannerDismissed: true }, 'none'],
        // Dismissing the banner has no effect on the takeover (the takeover has no dismiss).
        ['not set up, empty inbox, banner dismissed', { bannerDismissed: true }, 'takeover'],
    ])('%s', (_label, overrides, expected) => {
        expect(computeOnboardingMode({ ...base, ...overrides })).toBe(expected)
    })
})
