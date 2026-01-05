import {
    IconAtSign,
    IconBook,
    IconBrain,
    IconCheckbox,
    IconCreditCard,
    IconDocument,
    IconGlobe,
    IconMemory,
    IconSearch,
    IconShuffle,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconQuestionAnswer, IconRobot } from 'lib/lemon-ui/icons'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { isObject } from '~/lib/utils'
import { AgentMode, AssistantTool } from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import { EnhancedToolCall } from './Thread'
import { isAgentMode } from './maxTypes'

export interface DisplayFormatterContext {
    registeredToolMap: Record<string, ToolRegistration>
}

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
        { registeredToolMap }: DisplayFormatterContext
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
        displayFormatter: function readDataDisplayFormatter(
            toolCall: EnhancedToolCall,
            context: DisplayFormatterContext
        ) {
            if (this.subtools && 'kind' in toolCall.args && typeof toolCall.args.kind === 'string') {
                const { displayFormatter } = this.subtools[toolCall.args.kind]
                if (displayFormatter) {
                    return displayFormatter(toolCall, context)
                }
            }

            if (toolCall.status === 'completed') {
                return 'Searched data'
            }

            return 'Searching data...'
        },
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
            dashboards: {
                name: 'Search dashboards',
                description: 'Search dashboards for answers',
                icon: iconForType('product_analytics'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched dashboards'
                    }
                    return 'Searching dashboards...'
                },
            },
            cohorts: {
                name: 'Search cohorts',
                description: 'Search cohorts for answers',
                icon: iconForType('cohort'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched cohorts'
                    }
                    return 'Searching cohorts...'
                },
            },
            actions: {
                name: 'Search actions',
                description: 'Search actions for answers',
                icon: iconForType('action'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched actions'
                    }
                    return 'Searching actions...'
                },
            },
            experiments: {
                name: 'Search experiments',
                description: 'Search experiments for answers',
                icon: iconForType('experiment'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched experiments'
                    }
                    return 'Searching experiments...'
                },
            },
            feature_flags: {
                name: 'Search feature flags',
                description: 'Search feature flags for answers',
                icon: iconForType('feature_flag'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched feature flags'
                    }
                    return 'Searching feature flags...'
                },
            },
            notebooks: {
                name: 'Search notebooks',
                description: 'Search notebooks for answers',
                icon: iconForType('notebook'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched notebooks'
                    }
                    return 'Searching notebooks...'
                },
            },
            surveys: {
                name: 'Search surveys',
                description: 'Search surveys for answers',
                icon: iconForType('survey'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched surveys'
                    }
                    return 'Searching surveys...'
                },
            },
            error_tracking_issues: {
                name: 'Search error tracking issues',
                description: 'Search error tracking issues for answers',
                icon: iconForType('error_tracking'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched error tracking issues'
                    }
                    return 'Searching error tracking issues...'
                },
            },
            all: {
                name: 'Search all entities',
                description: 'Search all entities for answers',
                icon: <IconSearch />,
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Searched all entities'
                    }
                    return 'Searching all entities...'
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
        displayFormatter: function readDataDisplayFormatter(
            toolCall: EnhancedToolCall,
            context: DisplayFormatterContext
        ) {
            if (
                this.subtools &&
                isObject(toolCall.args?.query) &&
                toolCall.args.query &&
                'kind' in toolCall.args.query &&
                typeof toolCall.args.query.kind === 'string' &&
                toolCall.args.query.kind in this.subtools
            ) {
                const { displayFormatter } = this.subtools[toolCall.args.query.kind]
                if (displayFormatter) {
                    return displayFormatter(toolCall, context)
                }
            }

            if (toolCall.status === 'completed') {
                return 'Read data'
            }

            return 'Reading data...'
        },
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
            data_warehouse_schema: {
                name: 'Read data warehouse schema',
                description: 'Read data warehouse schema available in this project',
                icon: iconForType('data_warehouse'),
                displayFormatter: (toolCall) => {
                    if (toolCall.status === 'completed') {
                        return 'Read data warehouse schema'
                    }
                    return 'Reading data warehouse schema...'
                },
            },
            data_warehouse_table: {
                name: 'Read data warehouse table schema',
                description: 'Read data warehouse table schema for a specific table',
                icon: iconForType('data_warehouse'),
                displayFormatter: (toolCall) => {
                    const tableName =
                        isObject(toolCall.args?.query) && 'table_name' in toolCall.args.query
                            ? toolCall.args.query.table_name
                            : null

                    if (toolCall.status === 'completed') {
                        return tableName ? `Read schema for \`${tableName}\`` : 'Read data warehouse table schema'
                    }
                    return tableName
                        ? `Reading schema for \`${tableName}\`...`
                        : 'Reading data warehouse table schema...'
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
            insight: {
                name: 'Retrieve an insight',
                description: 'Retrieve an insight data',
                icon: iconForType('product_analytics'),
                displayFormatter: (toolCall) => {
                    function isExecuting(): boolean {
                        return !!(
                            isObject(toolCall.args?.query) &&
                            toolCall.args?.query &&
                            'execute' in toolCall.args?.query &&
                            toolCall.args?.query.execute
                        )
                    }

                    if (toolCall.status === 'completed') {
                        return isExecuting() ? 'Analyzed an insight' : 'Retrieved an insight'
                    }
                    return isExecuting() ? 'Analyzing an insight...' : 'Retrieving an insight...'
                },
            },
            dashboard: {
                name: 'Retrieve a dashboard',
                description: 'Retrieve a dashboard data',
                icon: iconForType('product_analytics'),
                displayFormatter: (toolCall) => {
                    function isExecuting(): boolean {
                        return !!(
                            isObject(toolCall.args?.query) &&
                            toolCall.args?.query &&
                            'execute' in toolCall.args?.query &&
                            toolCall.args?.query.execute
                        )
                    }

                    if (toolCall.status === 'completed') {
                        return isExecuting() ? 'Analyzed a dashboard' : 'Retrieved a dashboard'
                    }
                    return isExecuting() ? 'Analyzing a dashboard...' : 'Retrieving a dashboard...'
                },
            },
        },
    },
    create_insight: {
        name: 'Create an insight or edit an existing one',
        description: "Create an insight or edit an existing one you're viewing",
        icon: iconForType('product_analytics'),
        product: Scene.Insight,
        modes: [AgentMode.ProductAnalytics],
        displayFormatter: (toolCall, { registeredToolMap }) => {
            const isEditing = registeredToolMap.create_insight
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
    search_error_tracking_issues: {
        name: 'Search issues',
        description: 'Search issues in error tracking',
        product: Scene.ErrorTracking,
        icon: iconForType('error_tracking'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Found issues'
            }
            return 'Searching issues...'
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
    upsert_dashboard: {
        name: 'Create and edit dashboards',
        description: 'Create and edit dashboards with insights based on your requirements',
        product: Scene.Dashboard,
        icon: iconForType('dashboard'),
        displayFormatter: (toolCall) => {
            if (isObject(toolCall.args?.action) && toolCall.args?.action && 'dashboard_id' in toolCall.args?.action) {
                if (toolCall.status === 'completed') {
                    return 'Edited the dashboard'
                }
                return 'Editing the dashboard...'
            }

            if (toolCall.status === 'completed') {
                return 'Created the dashboard'
            }
            return 'Creating the dashboard...'
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
    create_task: {
        name: 'Create a task',
        description: 'Create a task for an AI agent to execute coding changes in a repository',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created task'
            }
            return 'Creating task...'
        },
    },
    run_task: {
        name: 'Run a task',
        description: 'Run a task to trigger its execution',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Started task execution'
            }
            return 'Starting task...'
        },
    },
    get_task_run: {
        name: 'Get task status',
        description: 'Get task status including stage, progress, and any errors',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Got task status'
            }
            return 'Getting task status...'
        },
    },
    get_task_run_logs: {
        name: 'Get task logs',
        description: 'Get task logs for debugging and reviewing execution details',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Got task logs'
            }
            return 'Getting task logs...'
        },
    },
    list_tasks: {
        name: 'List tasks',
        description: 'List tasks in the current project with optional filtering',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Listed tasks'
            }
            return 'Listing tasks...'
        },
    },
    list_task_runs: {
        name: 'List task runs',
        description: 'List task runs for a specific task to see execution history',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Listed task runs'
            }
            return 'Listing task runs...'
        },
    },
    list_repositories: {
        name: 'List repositories',
        description: 'List repositories available via GitHub integration for creating tasks',
        product: Scene.TaskTracker,
        icon: iconForType('task'),
        flag: FEATURE_FLAGS.PHAI_TASKS,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Listed repositories'
            }
            return 'Listing repositories...'
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
    web_search: {
        name: 'Search the web', // Web search is a special case of a tool, as it's a built-in LLM provider one
        description: 'Search the web for up-to-date information',
        icon: <IconGlobe />,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                // The args won't be fully streamed initially, so we need to check if `query` is present
                return toolCall.args.query ? `Searched the web for **${toolCall.args.query}**` : 'Searched the web'
            }
            return toolCall.args.query ? `Searching the web for **${toolCall.args.query}**...` : 'Searching the web...'
        },
        flag: FEATURE_FLAGS.PHAI_WEB_SEARCH,
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
    [AgentMode.ErrorTracking]: {
        name: 'Error tracking',
        description: 'Searches and analyzes error tracking issues to help you understand and fix bugs.',
        icon: iconForType('error_tracking'),
        scenes: new Set([Scene.ErrorTracking]),
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
export function getDefaultTools({ webSearchEnabled }: { webSearchEnabled: boolean }): ToolDefinition[] {
    const defaultTools = DEFAULT_TOOL_KEYS.map((key) => TOOL_DEFINITIONS[key])
    if (webSearchEnabled) {
        // Add web search after `search`
        defaultTools.splice(defaultTools.indexOf(TOOL_DEFINITIONS.search) + 1, 0, TOOL_DEFINITIONS.web_search)
    }
    return defaultTools
}

export type SpecialMode = keyof typeof SPECIAL_MODES

export const AI_GENERALLY_CAN: { icon: JSX.Element; description: string }[] = [
    { icon: <IconAtSign />, description: 'Analyze and use attached context' },
    { icon: <IconMemory />, description: 'Remember project-level information' },
]

export const AI_GENERALLY_CANNOT: string[] = [
    'Access your source code or third‑party tools',
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
