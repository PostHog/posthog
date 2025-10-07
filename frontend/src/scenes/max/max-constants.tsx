import { IconAtSign, IconBook, IconCompass, IconCreditCard, IconMemory, IconSearch } from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AssistantTool } from '~/queries/schema/schema-assistant-messages'

/** Static tool definition for display purposes. */
export interface ToolDefinition<N extends string = string> {
    /** A user-friendly display name for the tool. Must be a verb phrase, like "Create surveys" or "Search docs" */
    name: N
    /**
     * The tool's description, which must be a sentence that's an extension of the name,
     * e.g. "Create surveys in seconds"
     */
    description?: `${N} ${string}`
    completedDescription?: string
    /** If the tool has multiple kinds, you can specify them here
     * These will populate the tool summary list, instead of the tool itself
     */
    kinds?: Record<
        string, // identifier, should match the "kind" key in the tool call
        ToolDefinition
    >
    icon: JSX.Element
    /**
     * If only available in a specific product, specify it here.
     * We're using Scene instead of ProductKey, because that's more flexible (specifically for SQL editor there
     * isn't ProductKey.SQL_EDITOR, only ProductKey.DATA_WAREHOUSE - much clearer for users to say Scene.SQLEditor here)
     */
    product?: Scene
    /** If the tool is only available if a feature flag is enabled, you can specify it here. */
    flag?: (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]
}

/** Active instance of a tool. */
export interface ToolRegistration extends Pick<ToolDefinition, 'name' | 'description'> {
    /** A unique identifier for the tool */
    identifier: keyof typeof TOOL_DEFINITIONS
    /**
     * Optional specific @posthog/icons icon
     * @default <IconWrench />
     */
    /** Contextual data to be included for use by the LLM */
    context?: Record<string, any>
    /**
     * Optional: If this tool is the main one of the page, you can override Max's default intro headline and description when it's mounted.
     *
     * Note that if more than one mounted tool has an intro override, only one will take effect.
     */
    introOverride?: {
        /** The default is something like "How can I help you build?" - stick true to this question form. */
        headline: string
        /** The default is "Ask me about your product and your users." */
        description: string
    }
    /** Optional: When in context, the tool can add items to the pool of Max's suggested questions */
    suggestions?: string[]
    /** The callback function that will be executed with the LLM's tool call output */
    callback?: (toolOutput: any) => void | Promise<void>
}

export const TOOL_DEFINITIONS: Record<Exclude<AssistantTool, 'todo_write'>, ToolDefinition> = {
    session_summarization: {
        name: 'Summarize sessions',
        description: 'Summarize sessions to analyze real user behavior',
        flag: 'max-session-summarization',
        icon: iconForType('session_replay'),
    },
    create_dashboard: {
        name: 'Create dashboards',
        description: 'Create dashboards with insights based on your requirements',
        icon: iconForType('dashboard'),
    },
    search: {
        name: 'Search',
        icon: <IconSearch />,
        kinds: {
            docs: {
                name: 'Search docs',
                description: 'Search docs for answers regarding PostHog',
                icon: <IconBook />,
            },
            insights: {
                name: 'Search existing insights',
                description: 'Search existing insights for answers',
                icon: iconForType('product_analytics'),
            },
        },
    },
    read_taxonomy: {
        name: 'Read taxonomy',
        icon: iconForType('data_warehouse'),
    },
    read_data: {
        name: 'Read data',
        description: 'Read data from PostHog',
        icon: iconForType('data_warehouse'),
        kinds: {
            billing_info: {
                name: 'Read billing data',
                description: 'Check your billing data',
                icon: <IconCreditCard />,
            },
        },
    },
    navigate: {
        name: 'Navigate',
        description: 'Navigate to other places in PostHog',
        icon: <IconCompass />,
    },
    create_and_query_insight: {
        name: 'Edit the insight',
        description: "Edit the insight you're viewing",
        product: Scene.Insight,
        icon: iconForType('product_analytics'),
    },
    search_session_recordings: {
        name: 'Search recordings',
        description: 'Search recordings quickly',
        product: Scene.Replay,
        icon: iconForType('session_replay'),
    },
    generate_hogql_query: {
        name: 'Write and tweak SQL',
        description: 'Write and tweak SQL right there',
        product: Scene.SQLEditor,
        icon: iconForType('insight/hog'),
    },
    analyze_user_interviews: {
        name: 'Analyze user interviews',
        description: 'Analyze user interviews, summarizing pages of feedback, and extracting learnings',
        product: Scene.UserInterviews,
        flag: FEATURE_FLAGS.USER_INTERVIEWS,
        icon: iconForType('user_interview'),
    },
    create_hog_function_filters: {
        name: 'Set up function filters',
        description: 'Set up function filters for quick pipeline configuration',
        product: Scene.DataPipelines,
        icon: iconForType('data_warehouse'),
    },
    create_hog_transformation_function: {
        name: 'Write and tweak Hog code',
        description: 'Write and tweak Hog code of transformations',
        product: Scene.DataPipelines,
        icon: iconForType('data_warehouse'),
    },
    create_hog_function_inputs: {
        name: 'Manage function variables',
        description: 'Manage function variables in Hog functions',
        product: Scene.DataPipelines,
        icon: iconForType('data_warehouse'),
    },
    filter_error_tracking_issues: {
        name: 'Filter issues',
        description: 'Filter issues to dig into errors',
        product: Scene.ErrorTracking,
        icon: iconForType('error_tracking'),
    },
    find_error_tracking_impactful_issue_event_list: {
        name: 'Find impactful issues',
        description: 'Find impactful issues affecting your conversion, activation, or any other events',
        product: Scene.ErrorTracking,
        flag: FEATURE_FLAGS.ERROR_TRACKING_ISSUE_CORRELATION,
        icon: iconForType('error_tracking'),
    },
    experiment_results_summary: {
        name: 'Summarize experiment results',
        description: 'Summarize experiment results for a comprehensive rundown',
        product: Scene.Experiment,
        flag: 'experiments-ai-summary',
        icon: iconForType('experiment'),
    },
    create_survey: {
        name: 'Create surveys',
        description: 'Create surveys in seconds',
        product: Scene.Surveys,
        icon: iconForType('survey'),
    },
    analyze_survey_responses: {
        name: 'Analyze survey responses',
        description: 'Analyze survey responses to extract themes and actionable insights',
        product: Scene.Surveys,
        icon: iconForType('survey'),
    },
    create_message_template: {
        name: 'Create email templates',
        description: 'Create email templates from scratch or using a URL for inspiration',
        product: Scene.Messaging,
        icon: iconForType('messaging'),
    },
    fix_hogql_query: {
        name: 'Fix SQL',
        icon: iconForType('data_warehouse'),
    },
    edit_current_insight: {
        name: 'Edit the insight you are viewing',
        icon: iconForType('product_analytics'),
    },
    filter_revenue_analytics: {
        name: 'Filter revenue analytics',
        description: 'Filter revenue analytics to find the most impactful revenue insights',
        product: Scene.RevenueAnalytics,
        icon: iconForType('revenue_analytics'),
    },
}

export const MAX_GENERALLY_CAN: { icon: JSX.Element; description: string }[] = [
    { icon: <IconAtSign />, description: 'Analyze and use attached context' },
    { icon: <IconMemory />, description: 'Remember project-level information' },
]

export const MAX_GENERALLY_CANNOT: string[] = [
    'Access your source code or third‑party tools',
    'Browse the web beyond PostHog documentation',
    'See data outside this PostHog project',
    'Guarantee correctness',
    'Order tungsten cubes',
]
