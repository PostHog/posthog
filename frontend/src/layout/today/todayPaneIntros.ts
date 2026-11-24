import type { TodayRailPane } from './todayShellLogic'

export type TodayIntroPane = Exclude<TodayRailPane, 'home'>

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
        title: 'See what’s happening, and why',
        description: 'Dashboards, insights, SQL and replays of what your users do.',
    },
    people: {
        title: 'Know your users, and reach them',
        description: 'Persons, cohorts and accounts, plus tickets to reach them.',
    },
    release: {
        title: 'Change what users get, and check it worked',
        description: 'Feature flags, experiments and early access features.',
    },
    monitor: {
        title: 'Know when something breaks',
        description: 'Errors, logs, traces, metrics and the alerts on them.',
    },
    automate: {
        title: 'What should happen without you?',
        description: 'Workflows, destinations, subscriptions and scouts that run on a trigger or a schedule.',
    },
    data: {
        title: 'Bring in your data, define it and send it on',
        description: 'Sources, pipelines, the warehouse, the definitions that describe your data, and where it goes.',
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
