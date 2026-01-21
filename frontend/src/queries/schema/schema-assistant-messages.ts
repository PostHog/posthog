import type { MaxBillingContext } from 'scenes/max/maxBillingContextLogic'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import type { Category, NotebookInfo } from '~/types'
import type { InsightShortId } from '~/types'

import { DocumentBlock } from './schema-assistant-artifacts'
import type {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from './schema-assistant-queries'
import type {
    FunnelsQuery,
    HogQLQuery,
    QuerySchema,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsTopCustomersQuery,
    TrendsQuery,
} from './schema-general'

// re-export MaxBillingContext to make it available in the schema
export type { MaxBillingContext }

// re-export QuerySchema to make it available in the schema
export type AssistantQuerySchema = QuerySchema

// Define ProsemirrorJSONContent locally to avoid exporting the TipTap type into schema.json
// which leads to improper type naming
// This matches the TipTap/Prosemirror JSONContent structure
export interface ProsemirrorJSONContent {
    type?: string
    attrs?: Record<string, any>
    content?: ProsemirrorJSONContent[]
    marks?: {
        type: string
        attrs?: Record<string, any>
        [key: string]: any
    }[]
    text?: string
    [key: string]: any
}

export enum AssistantMessageType {
    Human = 'human',
    ToolCall = 'tool',
    Context = 'context',
    Assistant = 'ai',
    Reasoning = 'ai/reasoning',
    Visualization = 'ai/viz',
    MultiVisualization = 'ai/multi_viz',
    Artifact = 'ai/artifact',
    Failure = 'ai/failure',
    Notebook = 'ai/notebook',
    Planning = 'ai/planning',
    TaskExecution = 'ai/task_execution',
}

/** Source of artifact - determines which model to fetch from */
export enum ArtifactSource {
    /** Artifact created by the agent (stored in AgentArtifact) */
    Artifact = 'artifact',
    /** Reference to a saved insight (stored in Insight model) */
    Insight = 'insight',
    /** Legacy visualization message converted to artifact (content stored inline in state) */
    State = 'state',
}

/** Type of artifact content */
export enum ArtifactContentType {
    /** Visualization artifact (chart, graph, etc.) */
    Visualization = 'visualization',
    /** Notebook */
    Notebook = 'notebook',
}

export interface BaseAssistantMessage {
    id?: string
    parent_tool_call_id?: string
}

export interface HumanMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Human
    content: string
    ui_context?: MaxUIContext
    trace_id?: string
}

export interface AssistantFormOption {
    /** Button label, which is also the message that gets sent on click. */
    value: string
    /** 'primary', 'secondary', or 'tertiary' - default 'secondary' */
    variant?: string
    /** When href is set, the button opens the link rather than sending an AI message. */
    href?: string
}

export interface AssistantForm {
    options: AssistantFormOption[]
}

export interface MultiQuestionFormQuestionOption {
    /** The value to use when this option is selected */
    value: string
}

export interface MultiQuestionFormQuestion {
    /** Unique identifier for this question */
    id: string
    /** The question text to display */
    question: string
    /** Available answer options */
    options: MultiQuestionFormQuestionOption[]
    /** Whether to show a "Type your answer" option (default: true) */
    allow_custom_answer?: boolean
}

export interface MultiQuestionForm {
    /** The questions to ask */
    questions: MultiQuestionFormQuestion[]
}

export interface AssistantMessageMetadata {
    form?: AssistantForm
    /** Thinking blocks, as well as server_tool_use and web_search_tool_result ones. Anthropic format of blocks. */
    thinking?: Record<string, unknown>[]
}

export interface AssistantToolCall {
    id: string
    name: string
    args: Record<string, unknown>
    /**
     * `type` needed to conform to the OpenAI shape, which is expected by LangChain
     * @default "tool_call"
     */
    type: 'tool_call'
}

export interface AssistantMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Assistant
    content: string
    meta?: AssistantMessageMetadata
    tool_calls?: AssistantToolCall[]
}

export interface ReasoningMessage extends BaseAssistantMessage {
    /**
     * @deprecated The model should not be used
     */
    type: AssistantMessageType.Reasoning
    content: string
    substeps?: string[]
}

export interface ModeContext {
    type: 'mode'
    mode: AgentMode
}

export type ContextMessageMetadata = ModeContext | null

export interface ContextMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Context
    content: string
    meta?: ContextMessageMetadata
}

/**
 * The union type with all cleaned queries for the assistant. Only used for generating the schemas with an LLM.
 */
export type AnyAssistantGeneratedQuery =
    | AssistantTrendsQuery
    | AssistantFunnelsQuery
    | AssistantRetentionQuery
    | AssistantHogQLQuery

export interface VisualizationItem {
    /** @default '' */
    query: string
    plan?: string
    answer:
        | AnyAssistantGeneratedQuery
        | TrendsQuery
        | FunnelsQuery
        | RetentionQuery
        | HogQLQuery
        | RevenueAnalyticsGrossRevenueQuery
        | RevenueAnalyticsMetricsQuery
        | RevenueAnalyticsMRRQuery
        | RevenueAnalyticsTopCustomersQuery
    initiator?: string
}

export interface VisualizationMessage extends BaseAssistantMessage, VisualizationItem {
    type: AssistantMessageType.Visualization
    short_id?: InsightShortId
}

export interface FailureMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Failure
    content?: string
}

export interface NotebookUpdateMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Notebook
    notebook_id: string
    content: ProsemirrorJSONContent
    notebook_type?: Category
    conversation_notebooks?: NotebookInfo[]
    current_run_notebooks?: NotebookInfo[]
    tool_calls?: AssistantToolCall[]
}

export enum PlanningStepStatus {
    Pending = 'pending',
    InProgress = 'in_progress',
    Completed = 'completed',
}

export interface PlanningStep {
    /**
     * @deprecated The class should not be used
     */
    description: string
    status: PlanningStepStatus
}

export interface PlanningMessage extends BaseAssistantMessage {
    /**
     * @deprecated The class should not be used
     */
    type: AssistantMessageType.Planning
    steps: PlanningStep[]
}

export enum TaskExecutionStatus {
    Pending = 'pending',
    InProgress = 'in_progress',
    Completed = 'completed',
    Failed = 'failed',
}

export interface TaskExecutionItem {
    /**
     * @deprecated The class should not be used
     */
    id: string
    description: string
    prompt: string
    status: TaskExecutionStatus
    artifact_ids?: string[]
    progress_text?: string
    task_type: string
}

export interface TaskExecutionMessage extends BaseAssistantMessage {
    /**
     * @deprecated The class should not be used
     */
    type: AssistantMessageType.TaskExecution
    tasks: TaskExecutionItem[]
}

export interface MultiVisualizationMessage extends BaseAssistantMessage {
    type: AssistantMessageType.MultiVisualization
    visualizations: VisualizationItem[]
    commentary?: string
}

export interface VisualizationArtifactContent {
    content_type: ArtifactContentType.Visualization
    query: AnyAssistantGeneratedQuery | AssistantQuerySchema
    name?: string | null
    description?: string | null
    plan?: string | null
}

export interface NotebookArtifactContent {
    content_type: ArtifactContentType.Notebook
    /** Structured blocks for the notebook content */
    blocks: DocumentBlock[]
    /** Title for the notebook */
    title?: string | null
}

export type ArtifactContent = VisualizationArtifactContent | NotebookArtifactContent

/** Frontend artifact message containing enriched content field. Do not use in the backend. */
export interface ArtifactMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Artifact
    /** The ID of the artifact (short_id for both drafts and saved insights) */
    artifact_id: string
    /** Source of artifact - determines which model to fetch from */
    source: ArtifactSource
    /** Content of artifact */
    content: ArtifactContent
}

export type RootAssistantMessage =
    | VisualizationMessage
    | MultiVisualizationMessage
    | ArtifactMessage
    | ReasoningMessage
    | AssistantMessage
    | HumanMessage
    | FailureMessage
    | NotebookUpdateMessage
    | PlanningMessage
    | TaskExecutionMessage
    | AssistantToolCallMessage

export enum AssistantEventType {
    Status = 'status',
    Message = 'message',
    Conversation = 'conversation',
    Notebook = 'notebook',
    Update = 'update',
    Approval = 'approval',
}

export interface AssistantUpdateEvent {
    id: string
    tool_call_id: string
    content: string
}

export interface SubagentUpdateEvent {
    id: string
    tool_call_id: string
    content: AssistantToolCall
}

export enum AssistantGenerationStatusType {
    Acknowledged = 'ack',
    GenerationError = 'generation_error',
}

export interface AssistantGenerationStatusEvent {
    type: AssistantGenerationStatusType
}

export interface AssistantToolCallMessage extends BaseAssistantMessage {
    type: AssistantMessageType.ToolCall
    /**
     * Payload passed through to the frontend - specifically for calls of contextual tool.
     * Tool call messages without a ui_payload are not passed through to the frontend.
     */
    ui_payload?: Record<string, any>
    content: string
    tool_call_id: string
}

/** Status value indicating an operation requires user approval before execution */
export const PENDING_APPROVAL_STATUS = 'pending_approval' as const

/** Response returned when a tool operation requires user approval */
export interface DangerousOperationResponse {
    status: typeof PENDING_APPROVAL_STATUS
    proposalId: string
    toolName: string
    preview: string
    payload: Record<string, any>
}

export type ApprovalDecisionStatus = 'pending' | 'approved' | 'rejected' | 'auto_rejected'

export type ApprovalCardUIStatus = ApprovalDecisionStatus | 'approving' | 'rejecting'

export type AssistantTool =
    | 'search_session_recordings'
    | 'fix_hogql_query'
    | 'analyze_user_interviews'
    | 'create_hog_transformation_function'
    | 'create_hog_function_filters'
    | 'create_hog_function_inputs'
    | 'create_message_template'
    | 'filter_error_tracking_issues'
    | 'search_error_tracking_issues'
    | 'find_error_tracking_impactful_issue_event_list'
    | 'experiment_results_summary'
    | 'create_survey'
    | 'analyze_survey_responses'
    | 'create_dashboard'
    | 'edit_current_dashboard'
    | 'read_taxonomy'
    | 'search'
    | 'read_data'
    | 'todo_write'
    | 'filter_revenue_analytics'
    | 'filter_web_analytics'
    | 'create_feature_flag'
    | 'create_experiment'
    | 'create_task'
    | 'run_task'
    | 'get_task_run'
    | 'get_task_run_logs'
    | 'list_tasks'
    | 'list_task_runs'
    | 'list_repositories'
    | 'web_search'
    | 'execute_sql'
    | 'switch_mode'
    | 'summarize_sessions'
    | 'filter_session_recordings'
    | 'create_insight'
    | 'create_form'
    | 'task'
    | 'upsert_dashboard'
    | 'manage_memories'
    | 'create_notebook'
    | 'list_data'

export enum AgentMode {
    ProductAnalytics = 'product_analytics',
    SQL = 'sql',
    SessionReplay = 'session_replay',
    ErrorTracking = 'error_tracking',
}

export enum SlashCommandName {
    SlashInit = '/init',
    SlashRemember = '/remember',
    SlashUsage = '/usage',
    SlashFeedback = '/feedback',
    SlashTicket = '/ticket',
}

/** Exact possible `urls` keys for the `navigate` tool. */
// Extracted using the following Claude Code prompt, then tweaked manually:
// "
// List every key of objects `frontend/src/products.tsx::productUrls` and `frontend/src/scenes/urls.ts::urls`,
// whose function takes either zero arguments, or only optional arguments.
// Exclude scenes related to signup, login, onboarding, upsell or admin, as well as internal scenes, and ones about uploading files.
// Your only output should be a list of those string keys in TypeScript enum syntax.
// Once done, verify whether indeed each item of the output satisfies the criteria.
// "
export enum AssistantNavigateUrl {
    Actions = 'actions',
    Activity = 'activity',
    Alerts = 'alerts',
    Annotations = 'annotations',
    CreateAction = 'createAction',
    Cohorts = 'cohorts',
    Dashboards = 'dashboards',
    Database = 'database',
    EarlyAccessFeatures = 'earlyAccessFeatures',
    EventDefinitions = 'eventDefinitions',
    ErrorTracking = 'errorTracking',
    Experiments = 'experiments',
    FeatureFlags = 'featureFlags',
    Game368Hedgehogs = 'game368hedgehogs',
    Heatmaps = 'heatmaps',
    IngestionWarnings = 'ingestionWarnings',
    Insights = 'insights',
    InsightNew = 'insightNew',
    Pipeline = 'pipeline',
    ProjectHomepage = 'projectHomepage',
    PropertyDefinitions = 'propertyDefinitions',
    Max = 'max',
    Notebooks = 'notebooks',
    Replay = 'replay',
    ReplaySettings = 'replaySettings',
    RevenueAnalytics = 'revenueAnalytics',
    SavedInsights = 'savedInsights',
    Settings = 'settings',
    SqlEditor = 'sqlEditor',
    Surveys = 'surveys',
    SurveyTemplates = 'surveyTemplates',
    ToolbarLaunch = 'toolbarLaunch',
    WebAnalytics = 'webAnalytics',
    WebAnalyticsWebVitals = 'webAnalyticsWebVitals',
    WebAnalyticsHealth = 'webAnalyticsHealth',
    WebAnalyticsLive = 'webAnalyticsLive',
    Persons = 'persons',
}

export const ASSISTANT_NAVIGATE_URLS = new Set(Object.values(AssistantNavigateUrl))
