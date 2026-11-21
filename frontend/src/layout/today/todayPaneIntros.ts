import type { TodayRailPane } from './todayShellLogic'

// The warehouse pane's sidebar shows the open page's own tabs, so it has nothing for an intro to describe.
export type TodayIntroPane = Exclude<TodayRailPane, 'home' | 'warehouse'>

export interface TodayPaneIntroCopy {
    title: string
    description: string
}

export const TODAY_PANE_INTROS: Record<TodayIntroPane, TodayPaneIntroCopy> = {
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
        description: 'Persons, cohorts and accounts, plus tickets to reach them.',
    },
    release: {
        title: 'Change what users get',
        description: 'Roll out with feature flags, and check it worked with experiments.',
    },
    monitor: {
        title: 'Is anything broken?',
        description: 'Error tracking, logs, metrics and uptime, so you hear about problems.',
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

// pinned: keys in the user's server-side `has_seen_product_intro_for`. Renaming one shows that intro again to
// everyone who dismissed it.
export function todayPaneIntroKey(pane: TodayIntroPane): string {
    return `today_pane_intro_${pane}`
}
