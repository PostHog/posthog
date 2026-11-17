import type { TodayRailPane } from './todayShellLogic'

/** A pane that opens a sidebar. Home has none, so it has no intro. */
export type TodayIntroPane = Exclude<TodayRailPane, 'home'>

export interface TodayPaneIntro {
    title: string
    description: string
}

/** What each sidebar pane is for, shown at its top until a person dismisses it. */
export const TODAY_PANE_INTROS: Record<TodayIntroPane, TodayPaneIntro> = {
    spaces: {
        title: 'Work with PostHog AI',
        description: 'Ask questions, run tasks and pick up past chats.',
    },
    analytics: {
        title: "What's happening, and why?",
        description: 'Dashboards, insights, SQL and replays of what your users do.',
    },
    people: {
        title: 'Who are your users?',
        description: 'Persons, cohorts and accounts, plus surveys and support to reach them.',
    },
    release: {
        title: 'Change what users get',
        description: 'Roll out with feature flags, test with experiments, preview with early access.',
    },
    monitor: {
        title: 'Is anything broken?',
        description: 'Error tracking, logs and alerts, so you hear about problems.',
    },
    products: {
        title: 'Every product in one place',
        description: 'Find any PostHog product, and star the ones you use most.',
    },
    settings: {
        title: 'Set up PostHog',
        description: 'Settings for you, this project and your organization.',
    },
}
