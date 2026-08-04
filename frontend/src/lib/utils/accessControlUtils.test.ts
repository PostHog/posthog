import { getOnboardingRequiredDisabledReason } from 'lib/utils/accessControlUtils'

describe('getOnboardingRequiredDisabledReason', () => {
    // Regression guard: the sidebar must stop offering product destinations the onboarding
    // gate would immediately bounce the user out of, but must never disable an item the gate
    // already exempts (e.g. /settings), or one whose href can't be resolved statically.
    it.each<[string, { href?: string | (() => string) }, boolean, boolean]>([
        ['gate inactive: item stays enabled', { href: '/inbox' }, false, false],
        ['gate active, path not exempt: item is disabled', { href: '/inbox' }, true, true],
        ['gate active, path exempt (settings): item stays enabled', { href: '/settings/user' }, true, false],
        ['gate active, non-string href: item stays enabled', { href: () => '/inbox' }, true, false],
        ['gate active, no href: item stays enabled', {}, true, false],
    ])('%s', (_name, item, onboardingRequired, expectDisabled) => {
        const reason = getOnboardingRequiredDisabledReason(item, onboardingRequired)
        expect(Boolean(reason)).toBe(expectDisabled)
    })
})
