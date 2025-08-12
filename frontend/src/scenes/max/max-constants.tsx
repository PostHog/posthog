import {} from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { AssistantContextualTool } from '~/queries/schema/schema-assistant-messages'

import { IconAtSign, IconMemory } from '@posthog/icons'
import { Scene } from 'scenes/sceneTypes'

/** Static tool definition for display purposes. */
export interface ToolDefinition<N extends string = string> {
    /** A user-friendly display name for the tool. Must be a verb phrase, like "Create surveys" or "Search docs" */
    name: N
    /**
     * The tool's description, which must be a sentence that's an extension of the name,
     * e.g. "Create surveys in seconds"
     */
    description: `${N} ${string}`
    /**
     * If the tool is global, set explicitly to null. If only available in a specific product, specify it here.
     * We're using Scene instead of ProductKey, because that's more flexible (specifically for SQL editor there
     * isn't ProductKey.SQL_EDITOR, only ProductKey.DATA_WAREHOUSE - much clearer for users to say Scene.SQLEditor here)
     */
    product: Scene | null
    /** If the tool is only available if a feature flag is enabled, you can specify it here. */
    flag?: (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]
}

/** Active instance of a tool. */
export interface ToolRegistration extends Pick<ToolDefinition, 'name' | 'description'> {
    /** A unique identifier for the tool */
    identifier: AssistantContextualTool
    /**
     * Optional specific @posthog/icons icon
     * @default <IconWrench />
     */
    icon?: JSX.Element
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
    suggestions?: string[] // TODO: Suggestions aren't used yet, pending a refactor of maxLogic's allSuggestions
    /** The callback function that will be executed with the LLM's tool call output */
    callback?: (toolOutput: any) => void | Promise<void>
}

export const TOOL_DEFINITIONS: Omit<Record<AssistantContextualTool, ToolDefinition>, 'fix_hogql_query'> = {
    create_and_query_insight: {
        name: 'Edit the insight',
        description: "Edit the insight you're viewing",
        product: Scene.Insight,
    },
    search_docs: {
        name: 'Search docs',
        description: 'Search docs for answers regarding PostHog',
        product: null,
    },
    navigate: {
        name: 'Navigate',
        description: 'Navigate to other places in PostHog',
        product: null,
    },
    search_session_recordings: {
        name: 'Search recordings',
        description: 'Search recordings for interesting sessions',
        product: Scene.Replay,
    },
    generate_hogql_query: {
        name: 'Write and tweak SQL',
        description: 'Write and tweak SQL right there',
        product: Scene.SQLEditor,
    },
    analyze_user_interviews: {
        name: 'Analyze user interviews',
        description: 'Analyze user interviews, summarizing pages of feedback, and extracting learnings',
        product: Scene.UserInterviews,
        flag: FEATURE_FLAGS.USER_INTERVIEWS,
    },
    create_hog_function_filters: {
        name: 'Set up function filters',
        description: 'Set up function filters for quick pipeline configuration',
        product: Scene.DataPipelines,
    },
    create_hog_transformation_function: {
        name: 'Write and tweak Hog code',
        description: 'Write and tweak Hog code of transformations',
        product: Scene.DataPipelines,
    },
    create_hog_function_inputs: {
        name: 'Manage function variables',
        description: 'Manage function variables in Hog functions',
        product: Scene.DataPipelines,
    },
    search_error_tracking_issues: {
        name: 'Filter issues',
        description: 'Filter issues to dig into errors',
        product: Scene.ErrorTracking,
        flag: 'error-tracking-scene-max-tool',
    },
    experiment_results_summary: {
        name: 'Summarize experiment results',
        description: 'Summarize experiment results for a comprehensive rundown',
        product: Scene.Experiment,
        flag: 'experiments-ai-summary',
    },
    create_survey: {
        name: 'Create surveys',
        description: 'Create surveys in seconds',
        product: Scene.Surveys,
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
