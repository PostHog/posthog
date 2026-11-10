import { HotKeyOrModifier } from '~/types'

/** Something the user did that a step can wait for. The logic maps app actions onto these. */
export type InAppOnboardingSignal = 'command-opened-by-keyboard' | 'command-closed' | 'command-result-opened'

export interface InAppOnboardingStep {
    // pinned: sent as the `step` property on the onboarding events, so renaming it splits their history.
    key: string
    title: string
    description: string
    /** The keys the step asks for, shown as a keyboard shortcut. */
    keys?: HotKeyOrModifier[]
    signal: InAppOnboardingSignal
    /** How many times the signal has to happen before the step is done. */
    times: number
}

export interface InAppOnboardingFlow {
    // pinned: sent as the `flow` property on the onboarding events and used to key saved progress.
    key: string
    // pinned: persisted per user in `has_seen_product_intro_for`, so renaming it shows the flow again
    // to everyone who already finished or skipped it.
    seenKey: string
    title: string
    steps: InAppOnboardingStep[]
    completion: Pick<InAppOnboardingStep, 'title' | 'description' | 'keys'>
}

export const COMMAND_K_FLOW: InAppOnboardingFlow = {
    key: 'command-k',
    seenKey: 'in-app-onboarding-command-k',
    title: 'Learn search',
    steps: [
        {
            key: 'open',
            title: 'Open search',
            description: 'Search finds any page, insight, dashboard, person, or setting in PostHog.',
            keys: ['command', 'k'],
            signal: 'command-opened-by-keyboard',
            times: 1,
        },
        {
            key: 'close',
            title: 'Close it',
            description: 'Esc closes search and leaves you where you were.',
            keys: ['escape'],
            signal: 'command-closed',
            times: 1,
        },
        {
            key: 'practice',
            title: 'Practice it',
            description: 'Press it 3 more times. The same shortcut opens and closes search.',
            keys: ['command', 'k'],
            signal: 'command-opened-by-keyboard',
            times: 3,
        },
        {
            key: 'go',
            title: 'Go somewhere',
            description: 'Open search, type a page name like Dashboards, and press Enter to go there.',
            keys: ['enter'],
            signal: 'command-result-opened',
            times: 1,
        },
    ],
    completion: {
        title: "You're all set",
        description: 'Press it any time you need to find something.',
        keys: ['command', 'k'],
    },
}

/** Flows in the order they run. Only one shows at a time: the first the user has not finished or skipped. */
export const IN_APP_ONBOARDING_FLOWS: InAppOnboardingFlow[] = [COMMAND_K_FLOW]
