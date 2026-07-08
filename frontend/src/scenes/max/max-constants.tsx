import {
    IconAtSign,
    IconBook,
    IconBrain,
    IconCheckbox,
    IconCloud,
    IconCreditCard,
    IconDocument,
    IconGlobe,
    IconMemory,
    IconNotebook,
    IconNotification,
    IconPeople,
    IconPlug,
    IconSearch,
    IconShuffle,
} from '@posthog/icons'

import { FEATURE_FLAGS } from 'lib/constants'
import { IconQuestionAnswer, IconRobot } from 'lib/lemon-ui/icons'
import { isObject } from 'lib/utils/guards'
import { Scene } from 'scenes/sceneTypes'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    AgentMode,
    AssistantTool,
    AssistantToolCall,
    AssistantToolCallMessage,
    TaskExecutionStatus,
} from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import type { SessionSummarizationUpdate } from './messages/SessionSummarizationProgress'

export interface EnhancedToolCall extends AssistantToolCall {
    status: TaskExecutionStatus
    isLastPlanningMessage?: boolean
    updates?: string[]
    /** The tool call result message, if available */
    result?: AssistantToolCallMessage
}

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
    ) => string | [text: string, widgetDef: RecordingsWidgetDef | SessionSummarizationWidgetDef | null]
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
    /** If the tool is in alpha, set this to true to display an alpha badge */
    alpha?: boolean
    /** Agent modes this tool is available in (defined in backend presets) */
    modes?: AgentMode[]
    /**
     * Set for tools using ToolRegistration.clientExecution, so a pending call is resumed with
     * a refusal (instead of stranded) after the owning view deregistered the handler.
     */
    clientExecuted?: boolean
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
    /**
     * Optional: executes part of the tool client-side. Runs with the tool call's arguments when
     * the backend pauses via `MaxTool.request_client_execution()`; the returned result resumes
     * the conversation and becomes that call's return value. Keep results small (verdicts, ids):
     * they ride a Temporal resume payload capped at ~2MiB.
     */
    clientExecution?: (args: Record<string, any>) => Promise<Record<string, unknown>>
}

export interface RecordingsWidgetDef {
    widget: 'recordings'
    args: RecordingUniversalFilters
}

export interface SessionSummarizationWidgetDef {
    widget: 'session_summarization'
    args: { updates: SessionSummarizationUpdate[] }
}

/** Static mode definition for display purposes. */
export interface ModeDefinition {
    name: string
    description: string
    icon: JSX.Element
    /** Scenes that should trigger this agent mode */
    scenes?: Set<Scene>
    beta?: boolean
    alpha?: boolean
    /** Feature flag key that gates this mode. When set, the mode is only available if the flag is enabled. */
    flag?: keyof typeof FEATURE_FLAGS
}

/** Default tools available in all modes */
export const DEFAULT_TOOL_KEYS: (keyof typeof TOOL_DEFINITIONS)[] = [
    'read_taxonomy',
    'read_data',
    'list_data',
    'list_feature_flags',
    'search',
    'switch_mode',
    'list_llm_skills',
    'get_llm_skill',
    'get_llm_skill_file',
]

function skillStatusFormatter(
    toolCall: EnhancedToolCall,
    { completedLabel, pendingLabel, nameArgKey }: { completedLabel: string; pendingLabel: string; nameArgKey?: string }
): string {
    const rawName = nameArgKey ? toolCall.args?.[nameArgKey] : undefined
    const suffix = typeof rawName === 'string' && rawName ? ` "${rawName}"` : ''
    if (toolCall.status === 'completed') {
        return `${completedLabel}${suffix}`
    }
    return `${pendingLabel}${suffix}...`
}

export const TOOL_DEFINITIONS: Record<AssistantTool, ToolDefinition> = {
    call_mcp_server: {
        name: 'Call an MCP server',
        description: 'Call an MCP server',
        icon: <IconPlug />,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Called an MCP server'
            }
            return 'Calling an MCP server...'
        },
    },
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
            return title ? `Running a task (${title})...` : 'Running a task...'
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
    search: {
        name: 'Search PostHog data',
        description:
            'Search PostHog data for documentation, insights, dashboards, cohorts, actions, experiments, feature flags, notebooks, error tracking issues, surveys, and other.',
        icon: <IconSearch />,
        displayFormatter: function readDataDisplayFormatter(
            toolCall: EnhancedToolCall,
            context: DisplayFormatterContext
        ) {
            if (
                this.subtools &&
                'kind' in toolCall.args &&
                typeof toolCall.args.kind === 'string' &&
                toolCall.args.kind in this.subtools
            ) {
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
    list_data: {
        name: 'List data',
        description: 'List data with pagination to browse PostHog entities',
        icon: <IconSearch />,
        displayFormatter: (toolCall) => {
            const kind = typeof toolCall.args?.kind === 'string' ? toolCall.args.kind : null
            const offset = typeof toolCall.args?.offset === 'number' ? toolCall.args.offset : 0
            const entityLabel = (kind ? kind.replace(/_/g, ' ') : 'entities').toLowerCase()
            const pageInfo = offset > 0 ? ` (page ${Math.floor(offset / 100) + 1})` : ''

            if (toolCall.status === 'completed') {
                return `Listed ${entityLabel}${pageInfo}`
            }
            return `Listing ${entityLabel}${pageInfo}...`
        },
    },
    list_feature_flags: {
        name: 'List feature flags',
        description: 'List feature flags with their status, filterable by stale/enabled/disabled',
        icon: <IconSearch />,
        displayFormatter: (toolCall) => {
            const status = typeof toolCall.args?.status === 'string' ? toolCall.args.status : null
            const offset = typeof toolCall.args?.offset === 'number' ? toolCall.args.offset : 0
            const pageInfo = offset > 0 ? ` (page ${Math.floor(offset / 100) + 1})` : ''
            const label = status ? `${status} feature flags` : 'feature flags'
            return toolCall.status === 'completed' ? `Listed ${label}${pageInfo}` : `Listing ${label}${pageInfo}...`
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
        modes: [AgentMode.UserInterview],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Analyzed user interviews'
            }
            return 'Analyzing user interviews...'
        },
    },
    create_user_interview_topic: {
        name: 'Set up user interviews',
        description: 'Set up user interviews — plan a research topic, target participants, and draft questions',
        product: Scene.UserInterviews,
        flag: FEATURE_FLAGS.USER_INTERVIEWS,
        icon: iconForType('user_interview'),
        modes: [AgentMode.UserInterview],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created interview topic'
            }
            return 'Setting up interview topic...'
        },
    },
    create_hog_function_filters: {
        name: 'Set up function filters',
        description: 'Set up function filters for quick pipeline configuration',
        product: Scene.Transformations,
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
        product: Scene.Transformations,
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
        product: Scene.Transformations,
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
    upsert_account: {
        name: 'Manage accounts',
        description: 'Manage accounts by creating them or updating roles, properties, and tags',
        product: Scene.CustomerAnalytics,
        icon: iconForType('cohort'),
        modes: [AgentMode.CustomerAnalytics],
        displayFormatter: (toolCall) => {
            const action = toolCall.args?.action
            const isUpdate = isObject(action) && 'action' in action && action.action === 'update'
            if (isUpdate) {
                return toolCall.status === 'completed' ? 'Updated account' : 'Updating account...'
            }
            return toolCall.status === 'completed' ? 'Created account' : 'Creating account...'
        },
    },
    upsert_account_notebook: {
        name: 'Manage account notes',
        description: 'Manage account notes — call recaps, summaries, or edits to an existing note',
        product: Scene.CustomerAnalytics,
        icon: iconForType('notebook'),
        modes: [AgentMode.CustomerAnalytics],
        displayFormatter: (toolCall) => {
            const action = toolCall.args?.action
            const isUpdate = isObject(action) && 'action' in action && action.action === 'update'
            if (isUpdate) {
                return toolCall.status === 'completed' ? 'Updated account note' : 'Updating account note...'
            }
            return toolCall.status === 'completed' ? 'Created account note' : 'Creating account note...'
        },
    },
    open_account: {
        name: 'Open account',
        description: 'Open account details and tabs',
        product: Scene.CustomerAnalytics,
        icon: <IconPeople />,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Opened account'
            }
            return 'Opening account...'
        },
    },
    search_error_tracking_issues: {
        name: 'Search issues',
        description: 'Search issues in error tracking',
        product: Scene.ErrorTracking,
        icon: iconForType('error_tracking'),
        modes: [AgentMode.ErrorTracking],
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
    experiment_results_summary: {
        name: 'Summarize experiment results',
        description: 'Summarize experiment results for a comprehensive rundown',
        product: Scene.Experiment,
        icon: iconForType('experiment'),
        modes: [AgentMode.Flags],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Summarized experiment results'
            }
            return 'Summarizing experiment results...'
        },
    },
    experiment_session_replays_summary: {
        name: 'Summarize experiment session replays',
        description:
            'Summarize experiment session replays to analyze user behavior patterns across experiment variants using session recordings',
        product: Scene.Experiment,
        icon: iconForType('session_replay'),
        modes: [AgentMode.Flags],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Analyzed session replay patterns'
            }
            return 'Analyzing session replays...'
        },
    },
    summarize_replay_vision_summaries: {
        name: 'Summarize session summaries',
        description: 'Summarize session summaries across a Replay Vision summarizer scanner',
        icon: iconForType('session_replay'),
        modes: [AgentMode.SessionReplay],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Summarized session summaries'
            }
            return 'Summarizing session summaries...'
        },
    },
    draft_replay_vision_scanner_prompt: {
        name: 'Write scanner prompts',
        description: 'Write scanner prompts for Replay Vision scanners',
        icon: iconForType('session_replay'),
        modes: [AgentMode.SessionReplay],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Drafted scanner prompt'
            }
            return 'Drafting scanner prompt...'
        },
    },
    search_replay_vision_observations: {
        name: 'Search observations',
        description: "Search observations by the meaning of a Replay Vision scanner's model reasoning",
        icon: iconForType('session_replay'),
        modes: [AgentMode.SessionReplay],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Searched observations'
            }
            return 'Searching observations...'
        },
    },
    create_survey: {
        name: 'Create surveys',
        description: 'Create surveys in seconds',
        product: Scene.Surveys,
        icon: iconForType('survey'),
        modes: [AgentMode.Survey],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created surveys'
            }
            return 'Creating surveys...'
        },
    },
    edit_survey: {
        name: 'Edit survey',
        description: 'Edit survey',
        product: Scene.Surveys,
        icon: iconForType('survey'),
        modes: [AgentMode.Survey],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Edited survey'
            }
            return 'Editing survey...'
        },
    },
    analyze_survey_responses: {
        name: 'Analyze survey responses',
        description: 'Analyze survey responses to extract themes and actionable insights',
        product: Scene.Surveys,
        icon: iconForType('survey'),
        modes: [AgentMode.Survey],
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
    web_analytics_doctor: {
        name: 'Diagnose web analytics',
        description: 'Diagnose web analytics setup issues like missing pageviews or partial proxy coverage',
        product: Scene.WebAnalytics,
        icon: iconForType('web_analytics'),
        displayFormatter: (toolCall) => {
            return toolCall.status === 'completed' ? 'Diagnosed web analytics' : 'Diagnosing web analytics...'
        },
    },
    assess_heatmap: {
        name: 'Assess a heatmap',
        description:
            'Assess a heatmap for a page — click, rageclick, and scroll-depth data plus the elements under the hot spots — and recommend concrete changes',
        product: Scene.WebAnalytics,
        icon: iconForType('web_analytics'),
        displayFormatter: (toolCall) => {
            return toolCall.status === 'completed' ? 'Assessed heatmap' : 'Assessing heatmap...'
        },
    },
    marketing_diagnose_setup: {
        name: 'Diagnose marketing analytics',
        description:
            'Diagnose marketing analytics setup with a health check across data sources, attribution, and conversion goals',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Diagnosed marketing analytics' : 'Diagnosing marketing analytics...',
    },
    marketing_explain_conversion_goal: {
        name: 'Explain a conversion goal',
        description:
            'Explain a conversion goal by showing which events drove its count, broken down by source and integration',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Explained conversion goal' : 'Explaining conversion goal...',
    },
    marketing_list_conversion_goals: {
        name: 'List conversion goals',
        description: 'List conversion goals with their last-30d performance',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Listed conversion goals' : 'Listing conversion goals...',
    },
    marketing_list_data_sources: {
        name: 'List marketing data sources',
        description: 'List marketing data sources with platform-side health for every connected ad integration',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Listed marketing data sources' : 'Listing marketing data sources...',
    },
    marketing_audit_utm: {
        name: 'Audit UTM tagging',
        description: 'Audit UTM tagging to find issues that prevent attribution to ad platforms',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Audited UTM tagging' : 'Auditing UTM tagging...',
    },
    marketing_suggest_conversion_goals: {
        name: 'Suggest conversion goals',
        description: 'Suggest conversion goals by ranking custom events that are good candidates',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Suggested conversion goals' : 'Suggesting conversion goals...',
    },
    marketing_suggest_utm_mappings: {
        name: 'Suggest UTM mappings',
        description:
            'Suggest UTM mappings by detecting unmatched utm_source values and proposing custom_source_mappings entries',
        product: Scene.MarketingAnalytics,
        icon: iconForType('marketing_analytics'),
        displayFormatter: (toolCall) =>
            toolCall.status === 'completed' ? 'Suggested UTM mappings' : 'Suggesting UTM mappings...',
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
        modes: [AgentMode.Flags],
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
        modes: [AgentMode.Flags],
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
            if (toolCall.args.new_mode === AgentMode.Execution) {
                if (toolCall.status === 'completed') {
                    return 'Plan is complete, switching to execution mode'
                }
                return 'Finalizing plan...'
            } else if (toolCall.args.new_mode === AgentMode.Plan) {
                if (toolCall.status === 'completed') {
                    return 'Switched to plan mode'
                }
                return 'Switching to plan mode...'
            } else if (toolCall.args.new_mode === AgentMode.Research) {
                if (toolCall.status === 'completed') {
                    return 'Switched to research mode'
                }
                return 'Switching to research mode...'
            }
            // Use optional chaining since Plan and Research modes are not in MODE_DEFINITIONS
            const newMode = toolCall.args.new_mode as string
            const modeName =
                newMode in MODE_DEFINITIONS ? MODE_DEFINITIONS[newMode as keyof typeof MODE_DEFINITIONS].name : null
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
            return 'Writing a SQL query...'
        },
    },
    summarize_sessions: {
        name: 'Summarize sessions',
        description: 'Summarize sessions to analyze real user behavior',
        icon: iconForType('session_replay'),
        beta: true,
        modes: [AgentMode.SessionReplay],
        displayFormatter: (toolCall) => {
            const text = toolCall.status === 'completed' ? 'Summarized sessions' : 'Summarizing sessions...'
            // Parse structured updates from the tool call updates
            const updates = toolCall.updates
            if (updates && updates.length > 0) {
                const parsedUpdates: SessionSummarizationUpdate[] = []
                for (const update of updates) {
                    try {
                        const parsed = JSON.parse(update)
                        if (isObject(parsed) && (parsed.type === 'sessions_discovered' || parsed.type === 'progress')) {
                            parsedUpdates.push(parsed as unknown as SessionSummarizationUpdate)
                        }
                    } catch {
                        // Not a structured update, skip
                    }
                }
                if (parsedUpdates.length > 0) {
                    return [text, { widget: 'session_summarization', args: { updates: parsedUpdates } }]
                }
            }
            return text
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
    },
    manage_memories: {
        name: 'Manage memories',
        description: 'Manage memories to store and retrieve persistent information',
        icon: <IconMemory />,
    },
    create_notebook: {
        name: 'Create a document',
        description: 'Create a document to write down your thoughts',
        icon: iconForType('notebook'),
        displayFormatter: (toolCall) => {
            if (toolCall.args.draft_content) {
                if (toolCall.status === 'completed') {
                    return 'Created a draft document'
                }
                return 'Creating a draft document...'
            }
            if (toolCall.status === 'completed') {
                return 'Created a document'
            }
            return 'Creating a document...'
        },
    },
    upsert_alert: {
        name: 'Manage alerts',
        description: 'Manage alerts to monitor insight metrics',
        icon: <IconNotification />,
        product: Scene.Insight,
        modes: [AgentMode.ProductAnalytics],
        displayFormatter: (toolCall) => {
            if (isObject(toolCall.args?.action) && 'alert_id' in toolCall.args.action) {
                return toolCall.status === 'completed' ? 'Updated alert' : 'Updating alert...'
            }
            return toolCall.status === 'completed' ? 'Created alert' : 'Creating alert...'
        },
    },
    diagnose_proxy: {
        name: 'Diagnose reverse proxy',
        description: 'Diagnose reverse proxy stuck or erroring states',
        icon: <IconCloud />,
        displayFormatter: (toolCall) => {
            return toolCall.status === 'completed' ? 'Diagnosed reverse proxy' : 'Diagnosing reverse proxy...'
        },
    },
    finalize_plan: {
        name: 'Finalize plan',
        description: 'Finalize plan',
        icon: iconForType('notebook'),
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Finalized plan'
            }
            return 'Finalizing plan...'
        },
    },
    search_llm_traces: {
        name: 'Search LLM traces',
        description: 'Search LLM traces to analyze model usage, costs, latency, and errors',
        icon: iconForType('llm_analytics'),
        modes: [AgentMode.AIObservability],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Searched LLM traces'
            }
            return 'Searching LLM traces...'
        },
    },
    create_ai_trace_parser: {
        name: 'Create custom parsers',
        description: 'Create custom parsers to control how AI observability events are displayed',
        icon: iconForType('llm_analytics'),
        clientExecuted: true,
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Created a custom parser'
            }
            return 'Writing a custom parser...'
        },
    },
    run_hog_eval_test: {
        name: 'Test evaluation',
        description: 'Test evaluation code against sample events',
        product: Scene.AIObservabilityEvaluation,
        icon: iconForType('llm_evaluations'),
        modes: [AgentMode.AIObservability],
        displayFormatter: (toolCall) => {
            if (toolCall.status === 'completed') {
                return 'Tested evaluation code'
            }
            return 'Testing evaluation code...'
        },
    },
    list_llm_skills: {
        name: 'List shared skills',
        description: 'List shared skills stored for this team',
        icon: <IconBook />,
        displayFormatter: (toolCall) =>
            skillStatusFormatter(toolCall, {
                completedLabel: 'Listed shared skills',
                pendingLabel: 'Listing shared skills',
            }),
    },
    get_llm_skill: {
        name: 'Load shared skill',
        description: 'Load shared skill body and file manifest',
        icon: <IconBook />,
        displayFormatter: (toolCall) =>
            skillStatusFormatter(toolCall, {
                completedLabel: 'Loaded shared skill',
                pendingLabel: 'Loading shared skill',
                nameArgKey: 'skill_name',
            }),
    },
    get_llm_skill_file: {
        name: 'Load shared skill file',
        description: 'Load shared skill file bundled in a skill',
        icon: <IconBook />,
        displayFormatter: (toolCall) =>
            skillStatusFormatter(toolCall, {
                completedLabel: 'Loaded skill file',
                pendingLabel: 'Loading skill file',
                nameArgKey: 'file_path',
            }),
    },
    create_llm_skill: {
        name: 'Create shared skill',
        description: 'Create shared skill to save a reusable workflow',
        product: Scene.AIObservability,
        icon: <IconBook />,
        modes: [AgentMode.AIObservability],
        displayFormatter: (toolCall) =>
            skillStatusFormatter(toolCall, {
                completedLabel: 'Created shared skill',
                pendingLabel: 'Creating shared skill',
                nameArgKey: 'name',
            }),
    },
    update_llm_skill: {
        name: 'Update shared skill',
        description: 'Update shared skill by publishing a new version',
        product: Scene.AIObservability,
        icon: <IconBook />,
        modes: [AgentMode.AIObservability],
        displayFormatter: (toolCall) =>
            skillStatusFormatter(toolCall, {
                completedLabel: 'Updated shared skill',
                pendingLabel: 'Updating shared skill',
                nameArgKey: 'skill_name',
            }),
    },
    archive_llm_skill: {
        name: 'Archive shared skill',
        description: 'Archive shared skill to hide it from suggestions',
        product: Scene.AIObservability,
        icon: <IconBook />,
        modes: [AgentMode.AIObservability],
        displayFormatter: (toolCall) =>
            skillStatusFormatter(toolCall, {
                completedLabel: 'Archived shared skill',
                pendingLabel: 'Archiving shared skill',
                nameArgKey: 'skill_name',
            }),
    },
}

export const MODE_DEFINITIONS: Record<
    Exclude<AgentMode, AgentMode.Plan | AgentMode.Execution | AgentMode.Research | AgentMode.Sandbox>,
    ModeDefinition
> = {
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
    [AgentMode.Survey]: {
        name: 'Surveys',
        description: 'Creates and analyzes surveys to collect user feedback.',
        icon: iconForType('survey'),
        scenes: new Set([Scene.Surveys, Scene.Survey]),
    },
    [AgentMode.Flags]: {
        name: 'Flags',
        description: 'Creates and manages feature flags and experiments.',
        icon: iconForType('feature_flag'),
        scenes: new Set([
            Scene.FeatureFlags,
            Scene.FeatureFlag,
            Scene.EarlyAccessFeature,
            Scene.EarlyAccessFeatures,
            Scene.Experiment,
            Scene.Experiments,
            Scene.ExperimentsSharedMetric,
            Scene.ExperimentsSharedMetrics,
        ]),
    },
    [AgentMode.AIObservability]: {
        name: 'AI observability',
        description: 'Analyzes LLM traces and writes evaluation code for AI observability.',
        icon: iconForType('llm_analytics'),
        scenes: new Set([
            Scene.AIObservability,
            Scene.AIObservabilityTrace,
            Scene.AIObservabilityEvaluation,
            Scene.AIObservabilityEvaluations,
            Scene.AIObservabilityDataset,
            Scene.AIObservabilityDatasets,
            Scene.AIObservabilityPlayground,
            Scene.AIObservabilityUsers,
        ]),
    },
    [AgentMode.UserInterview]: {
        name: 'User interviews',
        description: 'Sets up live AI voice interviews and analyzes interview transcripts.',
        icon: iconForType('user_interview'),
        scenes: new Set([Scene.UserInterviews, Scene.UserInterview, Scene.UserInterviewResponse]),
        flag: 'USER_INTERVIEWS',
    },
    [AgentMode.CustomerAnalytics]: {
        name: 'Customer analytics',
        description:
            'Works with your customer accounts — assign owners, review notes and usage, and dig into account data.',
        icon: iconForType('cohort'),
        scenes: new Set([Scene.CustomerAnalytics]),
        flag: 'CUSTOMER_ANALYTICS_CSP',
    },
}

export const SPECIAL_MODES: Record<string, ModeDefinition> = {
    auto: {
        name: 'Auto',
        description:
            'Automatically selects the best mode based on your request. The tools that are available in all modes are listed below.',
        icon: <IconShuffle />,
    },
    plan: {
        name: 'Plan',
        description:
            "Creates a plan to guide the agent's actions and achieve your goals. The tools that are available in all modes are listed below.",
        icon: <IconNotebook />,
        beta: true,
    },
    research: {
        name: 'Research',
        description:
            'Answers complex questions using advanced reasoning models and more resources, taking more time to provide deeper insights.',
        icon: <IconBrain />,
        beta: true,
    },
    sandbox: {
        name: 'Sandbox',
        description: 'Spawns a cloud coding agent to work on the PostHog codebase.',
        icon: <IconCloud />,
        flag: 'PHAI_SANDBOX_MODE',
        alpha: true,
    },
}

/** Human-readable label for an agent or special mode value (e.g. `'product_analytics'` → `'Product analytics'`). */
export function getModeDisplayName(mode: string): string {
    return MODE_DEFINITIONS[mode as keyof typeof MODE_DEFINITIONS]?.name ?? SPECIAL_MODES[mode]?.name ?? mode
}

/** Get tools available for a specific agent mode */
export function getToolsForMode(mode: AgentMode): ToolDefinition[] {
    return Object.values(TOOL_DEFINITIONS).filter((tool) => tool.modes?.includes(mode))
}

/** Get default tools available in auto mode */
export function getDefaultTools(): ToolDefinition[] {
    const defaultTools = DEFAULT_TOOL_KEYS.map((key) => TOOL_DEFINITIONS[key])
    // Add web search after `search`
    defaultTools.splice(defaultTools.indexOf(TOOL_DEFINITIONS.search) + 1, 0, TOOL_DEFINITIONS.web_search)
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
    const definition = getToolDefinition(toolCall.name)
    // Only use args.kind for subtool lookup if the parent tool has subtools
    if (definition?.subtools && typeof toolCall.args.kind === 'string') {
        return definition.subtools[toolCall.args.kind] ?? definition
    }
    return definition
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
