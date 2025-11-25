import {
    IconAtSign,
    IconBook,
    IconBrain,
    IconCheckbox,
    IconCreditCard,
    IconDocument,
    IconMemory,
    IconSearch,
    IconShuffle,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconQuestionAnswer, IconRobot } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { AgentMode, AssistantTool } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { EnhancedToolCall } from './Thread'
import { isAgentMode } from './maxTypes'

/** Static tool definition for display purposes. */
export interface ToolDefinition<N extends string = string> {
    /** A user-friendly display name for the tool. Must be a verb phrase, like "Create surveys" or "Search docs" */
    name: N
    /**
     * The tool's description, which must be a sentence that's an extension of the name,
     * e.g. "Create surveys in seconds"
     */
    description?: `${N} ${string}`
    /** If the tool has multiple subtools, you can specify them here
     * These will populate the tool summary list, instead of the tool itself
     */
    subtools?: Record<
        string, // identifier, should match the "kind" key in the tool call
        ToolDefinition
    >
    icon: JSX.Element
    displayFormatter?: (
        toolCall: EnhancedToolCall,
        { registeredToolMap }: { registeredToolMap: Record<string, ToolRegistration> }
    ) => string | [text: string, widgetDef: RecordingsWidgetDef | null]
    /**
     * If only available in a specific product, specify it here.
     * We're using Scene instead of ProductKey, because that's more flexible (specifically for SQL editor there
     * isn't ProductKey.SQL_EDITOR, only ProductKey.DATA_WAREHOUSE - much clearer for users to say Scene.SQLEditor here)
     */
    product?: Scene
    /** If the tool is only available if a feature flag is enabled, you can specify it here. */
    flag?: (typeof FEATURE_FLAGS)[keyof typeof FEATURE_FLAGS]
    /** If the tool is in beta, set this to true to display a beta badge */
    beta?: boolean
    /** Agent modes this tool is available in (defined in backend presets) */
    modes?: AgentMode[]
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
     * Optional: Describes what kind of context information is being provided
     * This metadata is shown to users in the context topbar to indicate what contextual values are available
     */
    contextDescription?: {
        /** The type or category of context (e.g., "Current insight", "Active filters") */
        text: string
        /** Icon to display for the context type */
        icon: JSX.Element
    }
    /**
     * Optional: If this tool is the main one of the page, you can override the default intro headline and description when it's mounted.
     *
     * Note that if more than one mounted tool has an intro override, only one will take effect.
     */
    introOverride?: {
        /** The default is something like "How can I help you build?" - stick true to this question form. */
        headline: string
        /** The default is "Ask me about your product and your users." */
        description: string
    }
    /** Optional: When in context, the tool can add items to the pool of suggested questions */
    suggestions?: string[]
    /** The callback function that will be executed with the LLM's tool call output */
    callback?: (toolOutput: any, conversationId: string) => void | Promise<void>
}

export interface RecordingsWidgetDef {
    widget: 'recordings'
    args: RecordingUniversalFilters
}

/** Static mode definition for display purposes. */
export interface ModeDefinition {
    name: string
    description: string
    icon: JSX.Element
    /** Scenes that should trigger this agent mode */
    scenes: Set<Scene>
}

/** Default tools available in all modes */
export const DEFAULT_TOOL_KEYS: (keyof typeof TOOL_DEFINITIONS)[] = [
    'read_taxonomy',
    'read_data',
    'search',
    'switch_mode',
]

export const TOOL_DEFINITIONS: Record<AssistantTool, ToolDefinition> = {
    todo_write: {
        name: 'Write a todo',
        description: 'Write a todo to remember a task',
        icon: <IconCheckbox />,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return `Update the to-do list`
            }
            return `Updating the to-do list...`
        },
    },
    task: {
        name: 'Run an agent to perform a task',
        description: 'Run an agent to perform a task',
        icon: <IconRobot />,
        displayFormatter: (toolCall) => {
            const title = toolCall.args.title
            if (toolCall.status === 'completed') {
                return `Task (${title})`
            }
            return `Running a task (${title})...`
        },
    },
    create_form: {
        name: 'Create a form',
        description: 'Create a form to collect information from the user',
        icon: <IconQuestionAnswer />,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created a form'
            }
            return 'Creating a form...'
        },
    },
    session_summarization: {
        name: 'Summarize sessions',
        description: 'Summarize sessions to analyze real user behavior',
        flag: 'max-session-summarization',
        icon: iconForType('session_replay'),
        beta: true,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Summarized sessions'
            }
            return 'Summarizing sessions...'
        },
    },
    create_dashboard: {
        name: 'Create dashboards',
        description: 'Create dashboards with insights based on your requirements',
        icon: iconForType('dashboard'),
        modes: [AgentMode.ProductAnalytics],
    },
    search: {
        name: 'Search PostHog data',
        description:
            'Search PostHog data for documentation, insights, dashboards, cohorts, actions, experiments, feature flags, notebooks, error tracking issues, surveys, and other.',
        icon: <IconSearch />,
        subtools: {
            docs: {
                name: 'Search docs',
                description: 'Search docs for answers regarding PostHog',
                icon: <IconBook />,
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched docs'
                    }
                    return 'Searching docs...'
                },
            },
            insights: {
                name: 'Search existing insights',
                description: 'Search existing insights for answers',
                icon: iconForType('product_analytics'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched insights'
                    }
                    return 'Searching insights...'
                },
            },
        },
    },
    read_taxonomy: {
        name: 'Read data schema',
        description: 'Read data schema to retrieve events, properties, and sample property values',
        icon: iconForType('data_warehouse'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Read data schema'
            }
            return 'Reading data schema...'
        },
    },
    read_data: {
        name: 'Read data',
        description: 'Read data, such as your data warehouse schema and billed usage statistics',
        icon: iconForType('data_warehouse'),
        subtools: {
            billing_info: {
                name: 'Check your billing data',
                description: 'Check your billing data',
                icon: <IconCreditCard />,
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Read billing data'
                    }
                    return 'Reading billing data...'
                },
            },
            datawarehouse_schema: {
                name: 'Read your data warehouse schema',
                description: 'Read your data warehouse schema',
                icon: iconForType('data_warehouse'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Read data warehouse schema'
                    }
                    return 'Reading data warehouse schema...'
                },
            },
            artifacts: {
                name: 'Read conversation artifacts',
                description: 'Read conversation artifacts created by the agent',
                icon: <IconDocument />,
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Read conversation artifacts'
                    }
                    return 'Reading conversation artifacts...'
                },
            },
        },
    },
    create_and_query_insight: {
        name: 'Edit the insight',
        description: "Edit the insight you're viewing",
        icon: iconForType('product_analytics'),
        product: Scene.Insight,
        displayFormatter: (toolCall, { registeredToolMap }) => {
            const isEditing = registeredToolMap.create_and_query_insight || registeredToolMap.create_insight
            if (isEditing) {
                return toolCall.status === 'completed'
                    ? 'Edited the insight you are viewing'
                    : 'Editing the insight you are viewing...'
            }
            return toolCall.status === 'completed' ? 'Created an insight' : 'Creating an insight...'
        },
    },
    create_insight: {
        name: 'Create an insight or edit an existing one',
        description: "Create an insight or edit an existing one you're viewing",
        icon: iconForType('product_analytics'),
        product: Scene.Insight,
        modes: [AgentMode.ProductAnalytics],
        displayFormatter: (toolCall, { registeredToolMap }) => {
            const isEditing = registeredToolMap.create_and_query_insight || registeredToolMap.create_insight
            if (isEditing) {
                return toolCall.status === 'completed'
                    ? 'Edited the insight you are viewing'
                    : 'Editing the insight you are viewing...'
            }
            return toolCall.status === 'completed' ? 'Created an insight' : 'Creating an insight...'
        },
    },
    search_session_recordings: {
        name: 'Search recordings',
        description: 'Search recordings quickly',
        product: Scene.Replay,
        icon: iconForType('session_replay'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Searched recordings'
            }
            return 'Searching recordings...'
        },
    },
    filter_session_recordings: {
        name: 'Filter recordings',
        description: 'Filter recordings to find the most relevant ones',
        product: Scene.Replay,
        icon: iconForType('session_replay'),
        displayFormatter: (toolCall) => {
            const widgetDef = toolCall.args?.recordings_filters
                ? ({
                      widget: 'recordings',
                      args: toolCall.args.recordings_filters as RecordingUniversalFilters,
                  } as const)
                : null
            if (toolCall.status === 'completed') {
                return ['Filtered recordings', widgetDef]
            }
            return ['Filtering recordings...', widgetDef]
        },
    },
    generate_hogql_query: {
        name: 'Write and tweak SQL',
        description: 'Write and tweak SQL right there',
        product: Scene.SQLEditor,
        icon: iconForType('insight/hog'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Edited SQL'
            }
            return 'Writing and tweaking SQL...'
        },
    },
    analyze_user_interviews: {
        name: 'Analyze user interviews',
        description: 'Analyze user interviews, summarizing pages of feedback, and extracting learnings',
        product: Scene.UserInterviews,
        flag: FEATURE_FLAGS.USER_INTERVIEWS,
        icon: iconForType('user_interview'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Analyzed user interviews'
            }
            return 'Analyzing user interviews...'
        },
    },
    create_hog_function_filters: {
        name: 'Set up function filters',
        description: 'Set up function filters for quick pipeline configuration',
        product: Scene.DataPipelines,
        icon: iconForType('data_warehouse'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Set up function filters'
            }
            return 'Setting up function filters...'
        },
    },
    create_hog_transformation_function: {
        name: 'Write and tweak Hog code',
        description: 'Write and tweak Hog code of transformations',
        product: Scene.DataPipelines,
        icon: iconForType('data_warehouse'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Edited Hog code'
            }
            return 'Writing and tweaking Hog code...'
        },
    },
    create_hog_function_inputs: {
        name: 'Manage function variables',
        description: 'Manage function variables in Hog functions',
        product: Scene.DataPipelines,
        icon: iconForType('data_warehouse'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Managed function variables'
            }
            return 'Managing function variables...'
        },
    },
    filter_error_tracking_issues: {
        name: 'Filter issues',
        description: 'Filter issues to dig into errors',
        product: Scene.ErrorTracking,
        icon: iconForType('error_tracking'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Filtered issues'
            }
            return 'Filtering issues...'
        },
    },
    find_error_tracking_impactful_issue_event_list: {
        name: 'Find impactful issues',
        description: 'Find impactful issues affecting your conversion, activation, or any other events',
        product: Scene.ErrorTracking,
        flag: FEATURE_FLAGS.ERROR_TRACKING_ISSUE_CORRELATION,
        icon: iconForType('error_tracking'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Found impactful issues'
            }
            return 'Finding impactful issues...'
        },
    },
    error_tracking_explain_issue: {
        name: 'Explain an issue',
        description: 'Explain an issue by analyzing its stack trace',
        product: Scene.ErrorTracking,
        icon: iconForType('error_tracking'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Issue explained'
            }
            return 'Analyzing issue...'
        },
    },
    experiment_results_summary: {
        name: 'Summarize experiment results',
        description: 'Summarize experiment results for a comprehensive rundown',
        product: Scene.Experiment,
        flag: 'experiment-ai-summary',
        icon: iconForType('experiment'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Summarized experiment results'
            }
            return 'Summarizing experiment results...'
        },
    },
    create_survey: {
        name: 'Create surveys',
        description: 'Create surveys in seconds',
        product: Scene.Surveys,
        icon: iconForType('survey'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created surveys'
            }
            return 'Creating surveys...'
        },
    },
    analyze_survey_responses: {
        name: 'Analyze survey responses',
        description: 'Analyze survey responses to extract themes and actionable insights',
        product: Scene.Surveys,
        icon: iconForType('survey'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Analyzed survey responses'
            }
            return 'Analyzing survey responses...'
        },
    },
    create_message_template: {
        name: 'Create email templates',
        description: 'Create email templates from scratch or using a URL for inspiration',
        product: Scene.Workflows,
        icon: iconForType('workflows'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created email templates'
            }
            return 'Creating email templates...'
        },
    },
    fix_hogql_query: {
        name: 'Fix SQL',
        icon: iconForType('data_warehouse'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Fixed SQL'
            }
            return 'Fixing SQL...'
        },
    },
    filter_revenue_analytics: {
        name: 'Filter revenue analytics',
        description: 'Filter revenue analytics to find the most impactful revenue insights',
        product: Scene.RevenueAnalytics,
        icon: iconForType('revenue_analytics'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Filtered revenue analytics'
            }
            return 'Filtering revenue analytics...'
        },
    },
    filter_web_analytics: {
        name: 'Filter web analytics',
        description: 'Filter web analytics to analyze traffic patterns and user behavior',
        product: Scene.WebAnalytics,
        icon: iconForType('web_analytics'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Filtered web analytics'
            }
            return 'Filtering web analytics...'
        },
    },
    edit_current_dashboard: {
        name: 'Add an insight to the dashboard',
        description: "Add an insight to the dashboard you're viewing",
        product: Scene.Dashboard,
        icon: iconForType('dashboard'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Added an insight to the dashboard'
            }
            return 'Adding an insight to the dashboard...'
        },
    },
    create_feature_flag: {
        name: 'Create a feature flag',
        description: 'Create a feature flag in seconds',
        product: Scene.FeatureFlags,
        icon: iconForType('feature_flag'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created feature flag'
            }
            return 'Creating feature flag...'
        },
    },
    create_experiment: {
        name: 'Create an experiment',
        description: 'Create an experiment in seconds',
        product: Scene.Experiments,
        icon: iconForType('experiment'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created experiment'
            }
            return 'Creating experiment...'
        },
    },
    switch_mode: {
        name: 'Switch agent mode',
        description:
            'Switch agent mode to another specialized mode like product analytics, SQL, or session replay analysis',
        icon: <IconShuffle />,
        displayFormatter: (toolCall) => {
            const modeName = isAgentMode(toolCall.args.new_mode) ? MODE_DEFINITIONS[toolCall.args.new_mode].name : null
            const modeText = (modeName ? ` to the ${modeName} mode` : 'mode').toLowerCase()

            if (toolCall.status === 'completed') {
                return `Switched agent ${modeText}`
            }

            return `Switching agent ${modeText}...`
        },
    },
    execute_sql: {
        name: 'Write and tweak SQL',
        description: 'Write and tweak SQL right there',
        product: Scene.SQLEditor,
        icon: iconForType('insight/hog'),
        modes: [AgentMode.SQL],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Executed SQL'
            }
            return 'Writing an SQL query...'
        },
    },
    summarize_sessions: {
        name: 'Summarize sessions',
        description: 'Summarize sessions to analyze real user behavior',
        flag: 'max-session-summarization',
        icon: iconForType('session_replay'),
        beta: true,
        modes: [AgentMode.SessionReplay],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Summarized sessions'
            }
            return 'Summarizing sessions...'
        },
    },
}

export const MODE_DEFINITIONS: Record<AgentMode, ModeDefinition> = {
    [AgentMode.ProductAnalytics]: {
        name: 'Product analytics',
        description: 'Creates insights and dashboards to analyze your product data.',
        icon: iconForType('product_analytics'),
        scenes: new Set([Scene.Dashboards, Scene.Dashboard, Scene.Insight, Scene.SavedInsights]),
    },
    [AgentMode.SQL]: {
        name: 'SQL',
        description: 'Generates and executes SQL queries for your PostHog data and connected data warehouse sources.',
        icon: iconForType('sql_editor'),
        scenes: new Set([Scene.SQLEditor]),
    },
    [AgentMode.SessionReplay]: {
        name: 'Session replay',
        description: 'Analyzes session recordings and provides summaries and insights about user behavior.',
        icon: iconForType('session_replay'),
        scenes: new Set([
            Scene.Replay,
            Scene.ReplaySingle,
            Scene.ReplayPlaylist,
            Scene.ReplayFilePlayback,
            Scene.ReplaySettings,
        ]),
    },
}

export const SPECIAL_MODES = {
    auto: {
        name: 'Auto',
        description:
            'Automatically selects the best mode based on your request. The tools that are available in all modes are listed below.',
        icon: <IconShuffle />,
    },
    deep_research: {
        name: 'Research',
        description:
            'Answers complex questions using advanced reasoning models and more resources, taking more time to provide deeper insights.',
        icon: <IconBrain />,
    },
}

/** Get tools available for a specific agent mode */
export function getToolsForMode(mode: AgentMode): ToolDefinition[] {
    return Object.values(TOOL_DEFINITIONS).filter((tool) => tool.modes?.includes(mode))
}

/** Get default tools available in auto mode */
export function getDefaultTools(): ToolDefinition[] {
    return DEFAULT_TOOL_KEYS.map((key) => TOOL_DEFINITIONS[key])
}

export type SpecialMode = keyof typeof SPECIAL_MODES

export const AI_GENERALLY_CAN: { icon: JSX.Element; description: string }[] = [
    { icon: <IconAtSign />, description: 'Analyze and use attached context' },
    { icon: <IconMemory />, description: 'Remember project-level information' },
]

export const AI_GENERALLY_CANNOT: string[] = [
    'Access your source code or third‑party tools',
    'Browse the web beyond PostHog documentation',
    'See data outside this PostHog project',
    'Guarantee correctness',
    'Order tungsten cubes',
]

export function getToolDefinitionFromToolCall(toolCall: EnhancedToolCall): ToolDefinition | null {
    const identifier = toolCall.args.kind ?? toolCall.name
    return getToolDefinition(identifier as string)
}

export function getToolDefinition(identifier: string): ToolDefinition | null {
    const flatTools = Object.entries(TOOL_DEFINITIONS).flatMap(([key, tool]) => {
        if (tool.subtools) {
            return [{ ...tool, key }, ...Object.entries(tool.subtools).map(([key, value]) => ({ ...value, key }))]
        }
        return [{ ...tool, key }]
    })
    let definition = flatTools.find((tool) => tool.key === identifier)
    if (!definition) {
        return null
    }
    return definition
}
