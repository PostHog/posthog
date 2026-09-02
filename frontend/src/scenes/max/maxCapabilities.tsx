import { IconBook } from '@posthog/icons'

import { urls } from 'scenes/urls'

import { FileSystemIconType } from '~/queries/schema/schema-general'

/** One suggestion inside a capability. `content` is the prompt sent to PostHog AI. */
export interface CapabilitySuggestion {
    /**
     * The prompt sent to PostHog AI. For `requiresUserInput` cards this is the instruction prefix
     * (no trailing "…"); the input shows it as a hint and the user's text is appended on send.
     * For docs-style capabilities this is also the text shown in the list.
     */
    content: string
    /** Card-style display; omit for docs-style capabilities (which render `content` as plain text). */
    title?: string
    description?: string
    /**
     * When set, this is a fill-in prompt: `content` is typed into the input, then this hint is shown
     * as a faded postfix (e.g. "insert feature flag name") after a wide caret, prompting the user to
     * complete it. `requiresUserInput` must also be true.
     */
    requiresUserInput?: boolean
    hint?: string
    /** Icon override for the card; falls back to the capability's icon. */
    iconType?: FileSystemIconType
}

export interface Capability {
    key: string
    label: string
    iconType: FileSystemIconType
    /** Badge icon override (e.g. for Learn, which has no product icon). */
    icon?: JSX.Element
    /**
     * 'cards' (default): icon + title + description cards. 'docs': a plain question list (like
     * production's Docs suggestions) so it reads as an explanation, not an action. Card-style
     * capabilities should have exactly 4 suggestions so every block is the same height.
     */
    variant?: 'cards' | 'docs'
    suggestions: CapabilitySuggestion[]
}

/** Shared across both experiment arms — routes to the PostHog Desktop beta in the inbox. */
export const CODE_CAPABILITY = {
    key: 'code',
    label: 'Code',
    to: urls.inbox(),
    beta: true as const,
}

/**
 * A few docs prompts included in every arm so newcomers can learn about PostHog. Rendered as a
 * plain question list (docs variant), matching the Docs suggestions we show in production.
 */
const LEARN_CAPABILITY: Capability = {
    key: 'learn',
    label: 'Learn',
    iconType: 'default_icon_type',
    icon: <IconBook />,
    variant: 'docs',
    suggestions: [
        { content: 'How can I create a feature flag?' },
        { content: 'Where do I watch session replays?' },
        { content: 'Help me set up an experiment' },
        { content: 'Explain autocapture' },
        { content: 'How can I capture an exception?' },
    ],
}

/**
 * Capability badges on the homepage and the PostHog AI sidebar, one per PostHog product. Prompt
 * content is drawn from the existing `QUESTION_SUGGESTIONS_DATA` on the PostHog AI scene so the
 * two surfaces stay in sync.
 */
export const HOMEPAGE_CAPABILITIES: Capability[] = [
    {
        key: 'analytics',
        label: 'Analytics',
        iconType: 'product_analytics',
        suggestions: [
            {
                title: 'Run a funnel analysis',
                description: 'Conversion and drop-off across the Pirate Metrics (AARRR)',
                content: 'Create a funnel of the Pirate Metrics (AARRR)',
            },
            {
                title: 'Check retention',
                description: 'How many users came back over the last two weeks',
                content: 'What is the retention in the last two weeks?',
            },
            {
                title: 'Find popular pages',
                description: 'Your most visited pages and screens',
                content: 'What are the most popular pages or screens?',
            },
            {
                title: 'See top referrers',
                description: 'Where your traffic is coming from',
                content: 'What are the top referring domains?',
            },
        ],
    },
    {
        key: 'sql',
        label: 'SQL',
        iconType: 'sql_editor',
        suggestions: [
            {
                title: 'Write a SQL query',
                description: 'Query any of your data with HogQL',
                content: 'Write an SQL query to',
                requiresUserInput: true,
                hint: 'type a question you have about your data',
            },
            {
                title: 'Explore your warehouse',
                description: 'Query your synced external data sources',
                content: 'Show me the tables available in my data warehouse',
            },
            {
                title: 'Find your top events',
                description: 'Your most frequent events this week',
                content: 'Write a SQL query for my most frequent events in the last 7 days',
            },
            {
                title: 'Count active users',
                description: 'Weekly active users with SQL',
                content: 'Write a SQL query to count my weekly active users',
            },
        ],
    },
    {
        key: 'session_replay',
        label: 'Session replay',
        iconType: 'session_replay',
        suggestions: [
            {
                title: 'Find recordings',
                description: 'Filter replays by user or action',
                content: 'Find recordings for',
                requiresUserInput: true,
                hint: 'type a specific user or behavior you wanna find recordings for',
            },
            {
                title: 'Summarize sessions',
                description: 'What happened across recent replays',
                content: 'Summarize recent session recordings and highlight anything notable',
            },
            {
                title: 'Spot friction',
                description: 'Rage-clicks, dead-clicks, and confusion',
                content: 'Find session replays showing common user pain points or confusion',
            },
            {
                title: 'Watch error sessions',
                description: 'Replays where users hit an error',
                content: 'Find session recordings where users ran into errors',
                iconType: 'error_tracking',
            },
        ],
    },
    {
        key: 'error_tracking',
        label: 'Error tracking',
        iconType: 'error_tracking',
        suggestions: [
            {
                title: 'Find impactful errors',
                description: 'The exceptions hitting the most users',
                content: 'What are the most impactful errors affecting my users right now?',
            },
            {
                title: 'Triage new issues',
                description: 'Errors first seen this week',
                content: 'Show me new error issues from the last 7 days',
            },
            {
                title: 'Explain an error',
                description: 'Likely cause and where it fires',
                content: 'Explain the most common error in my app and where it happens',
            },
            {
                title: 'See error replays',
                description: 'Watch sessions where users hit an error',
                content: 'Find session recordings where users ran into errors',
                iconType: 'session_replay',
            },
        ],
    },
    {
        key: 'feature_flags',
        label: 'Feature flags',
        iconType: 'feature_flag',
        suggestions: [
            {
                title: 'Roll out a feature',
                description: 'Gradually release a feature behind a flag',
                content: 'Create a flag to gradually roll out',
                requiresUserInput: true,
                hint: "type the feature you're launching",
            },
            {
                title: 'Create a multivariate flag',
                description: 'Test several variants of a feature',
                content: 'Create a multivariate flag for',
                requiresUserInput: true,
                hint: "type the feature you're testing",
            },
            {
                title: 'Audit your flags',
                description: 'Find stale or risky feature flags',
                content: 'Audit my feature flags for issues',
            },
            {
                title: 'Review flag usage',
                description: 'Which flags are still being evaluated',
                content: 'Which of my feature flags are still being evaluated?',
            },
        ],
    },
    {
        key: 'experiments',
        label: 'Experiments',
        iconType: 'experiment',
        suggestions: [
            {
                title: 'Design an A/B test',
                description: 'Set up an experiment to test a change',
                content: 'Create an experiment to test',
                requiresUserInput: true,
                hint: 'type a change you have in mind',
            },
            {
                title: 'Review a running test',
                description: 'Check your experiments are set up correctly',
                content: 'Check if my running experiments are set up correctly',
            },
            {
                title: 'Interpret results',
                description: 'Significance and what to do next',
                content: 'Summarize the results of my most recent experiment and what to do next',
            },
            {
                title: 'Size an experiment',
                description: 'How long it needs to run for significance',
                content: 'How long should my experiment run to reach significance?',
            },
        ],
    },
    {
        key: 'surveys',
        label: 'Surveys',
        iconType: 'survey',
        suggestions: [
            {
                title: 'Launch an NPS survey',
                description: 'Collect Net Promoter Score from your users',
                content: 'Create a survey to collect NPS responses from users',
            },
            {
                title: 'Run a CSAT survey',
                description: 'Measure customer satisfaction',
                content: 'Create a survey to collect CSAT responses from users',
            },
            {
                title: 'Measure product-market fit',
                description: 'Ask how users would feel without your product',
                content: 'Create a survey to measure product market fit',
            },
            {
                title: 'Analyze survey responses',
                description: 'Surface themes to prioritize what to build',
                content: 'Analyze survey responses to prioritize key features our users are interested in',
            },
        ],
    },
    LEARN_CAPABILITY,
]
