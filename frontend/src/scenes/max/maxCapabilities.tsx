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

/** Shared across both experiment arms — routes to the PostHog Code beta in the inbox. */
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
 * Product-based grouping — mirrors PostHog's products. Prompt content is drawn from the
 * existing `QUESTION_SUGGESTIONS_DATA` on the PostHog AI scene so the two surfaces stay in sync.
 */
export const PRODUCT_CAPABILITIES: Capability[] = [
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

/**
 * Behavior-based grouping — organized around what people come to PostHog to *do*, rather than
 * which product a task lives in. Same underlying prompts, regrouped by job-to-be-done.
 */
export const BEHAVIOR_CAPABILITIES: Capability[] = [
    {
        key: 'analyze',
        label: 'Analyze',
        iconType: 'product_analytics',
        suggestions: [
            {
                title: 'Run a feature analysis',
                description: 'Adoption, engagement, and retention of a feature',
                content: 'Run a feature analysis covering adoption, engagement, and retention',
            },
            {
                title: 'Summarize product usage',
                description: 'Top events, active users, and key funnels',
                content: 'Summarize our product usage: top events, active users, and key funnels',
            },
            {
                title: 'Check retention',
                description: 'How many users came back over the last two weeks',
                content: 'What is the retention in the last two weeks?',
            },
            {
                title: 'Query with SQL',
                description: 'Ask anything of your data with HogQL',
                content: 'Write an SQL query to',
                requiresUserInput: true,
                hint: 'type a question you have about your data',
                iconType: 'sql_editor',
            },
        ],
    },
    {
        key: 'debug',
        label: 'Debug',
        iconType: 'error_tracking',
        suggestions: [
            {
                title: 'Find impactful errors',
                description: 'The exceptions hitting the most users',
                content: 'What are the most impactful errors affecting my users right now?',
            },
            {
                title: 'Investigate a drop',
                description: 'Root-cause a recent change in a metric',
                content: 'Investigate why one of my key metrics dropped last week',
            },
            {
                title: 'Watch error sessions',
                description: 'Replays where users ran into a problem',
                content: 'Find session recordings where users ran into errors',
                iconType: 'session_replay',
            },
            {
                title: 'Explain an error',
                description: 'Likely cause and where it fires',
                content: 'Explain the most common error in my app and where it happens',
            },
        ],
    },
    {
        key: 'monitor',
        label: 'Monitor',
        iconType: 'session_replay',
        suggestions: [
            {
                title: 'Summarize recent sessions',
                description: 'Common patterns across recent replays',
                content: 'Summarize recent session recordings and highlight anything notable',
            },
            {
                title: 'Spot friction',
                description: 'Where users hesitate, rage-click, or churn',
                content: 'Find session replays showing common user pain points or confusion',
            },
            {
                title: 'Review conversion',
                description: 'How your main funnel performed this week',
                content: 'How is my main conversion funnel performing this week?',
            },
            {
                title: 'Watch a user journey',
                description: 'Replays for a specific segment or action',
                content: 'Find recordings for',
                requiresUserInput: true,
                hint: 'type a specific user or behavior you wanna find recordings for',
            },
        ],
    },
    {
        key: 'ship',
        label: 'Ship',
        iconType: 'feature_flag',
        suggestions: [
            {
                title: 'Roll out a feature',
                description: 'Gradually release behind a flag',
                content: 'Create a flag to gradually roll out',
                requiresUserInput: true,
                hint: "type the feature you're launching",
            },
            {
                title: 'Run an A/B test',
                description: 'Experiment to measure the impact of a change',
                content: 'Create an experiment to test',
                requiresUserInput: true,
                hint: 'type a change you have in mind',
                iconType: 'experiment',
            },
            {
                title: 'Audit your flags',
                description: 'Find stale or risky feature flags',
                content: 'Audit my feature flags for issues',
            },
            {
                title: 'Plan a release',
                description: 'Draft a safe gradual rollout',
                content: 'Help me plan a safe gradual rollout for a new feature',
            },
        ],
    },
    {
        key: 'understand',
        label: 'Understand',
        iconType: 'survey',
        suggestions: [
            {
                title: 'Ask users a question',
                description: 'Launch an NPS, CSAT, or custom survey',
                content: 'Create a survey to collect NPS responses from users',
            },
            {
                title: 'Measure product-market fit',
                description: 'Ask how users would feel without your product',
                content: 'Create a survey to measure product market fit',
            },
            {
                title: 'Summarize feedback',
                description: 'Common themes across recent responses',
                content: 'Analyze survey responses to prioritize key features our users are interested in',
            },
            {
                title: 'Learn from interviews',
                description: 'Key themes across user interviews',
                content: 'Analyze my user interviews and summarize the key themes',
            },
        ],
    },
    LEARN_CAPABILITY,
]

export type CapabilityGrouping = 'behaviors' | 'products'

export function capabilitiesForGrouping(grouping: CapabilityGrouping): Capability[] {
    return grouping === 'behaviors' ? BEHAVIOR_CAPABILITIES : PRODUCT_CAPABILITIES
}

/** Maps the `MAX_HOMEPAGE_CAPABILITIES` experiment variant to a grouping (null = control). */
export function capabilityGroupingFromVariant(variant: string | boolean | undefined): CapabilityGrouping | null {
    return variant === 'behaviors' || variant === 'products' ? variant : null
}
