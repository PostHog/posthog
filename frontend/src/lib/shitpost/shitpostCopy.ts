import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

// Shitpost mode (hackathon): when the `shitpost-mode` feature flag is on, UI copy that
// passes through a shared component (starting with `LemonButton`) is rewritten to a
// slightly shitpost-y equivalent. This is deliberately a thin, opt-in interception layer
// rather than a real i18n framework — PostHog has no string catalogue, so this doubles as a
// proof of concept for "what a central copy layer could hook into".

// Keys are the original copy lower-cased and trimmed; values are the replacement in the
// casing we want rendered (Sentence case, to match the app's convention).
const SHITPOST_DICTIONARY: Record<string, string> = {
    dismiss: 'This is trash',
    cancel: 'Nope',
    save: 'Yeet it',
    'save changes': 'Yeet the changes',
    'save & close': 'Yeet and dip',
    delete: 'Obliterate',
    submit: 'Send it',
    confirm: 'Absolutely',
    continue: 'Onward',
    create: 'Manifest',
    done: 'Ship it',
    retry: 'Do it again',
    close: 'Begone',
    upgrade: 'Take my money',
    'learn more': 'Teach me',
    'get started': "Let's gooo",
    'load more': 'Gimme more',
    apply: 'Make it so',
    reset: 'Nuke it',
    export: 'Yoink the data',
    yes: 'Hell yes',
    no: 'Hard pass',
    back: 'Retreat',
    next: 'Onwards',
    edit: 'Tinker',
    copy: 'Steal this',
    refresh: 'Bonk it',
    'try again': 'Have another go',
}

/**
 * Whether shitpost mode is currently active.
 *
 * Reads the flag via `findMounted()` rather than a kea subscription so it stays safe to call
 * from low-level shared components (e.g. `LemonButton`) in any render context, including
 * Storybook where `featureFlagLogic` may not be mounted. Returns `false` when the logic isn't
 * mounted, which keeps the feature off by default.
 */
export function isShitpostModeEnabled(): boolean {
    const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags
    return !!featureFlags?.[FEATURE_FLAGS.SHITPOST_MODE]
}

/**
 * Rewrite a single piece of button copy to its shitpost-y equivalent.
 * Returns the input unchanged when there is no mapping, so it is always safe to call.
 */
export function shitpostify(text: string): string {
    return SHITPOST_DICTIONARY[text.trim().toLowerCase()] ?? text
}
