import type { MaxBillingContext } from 'scenes/max/maxBillingContextLogic'
import type { MaxUIContext } from 'scenes/max/maxTypes'

import { InsightShortId } from '~/types'

import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from './schema-assistant-queries'
import { FunnelsQuery, HogQLQuery, RetentionQuery, TrendsQuery } from './schema-general'

// re-export MaxBillingContext to make it available in the schema
export type { MaxBillingContext }

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
    Assistant = 'ai',
    Reasoning = 'ai/reasoning',
    Visualization = 'ai/viz',
    MultiVisualization = 'ai/multi_viz',
    Failure = 'ai/failure',
    Notebook = 'ai/notebook',
    Planning = 'ai/planning',
    TaskExecution = 'ai/task_execution',
}

export interface BaseAssistantMessage {
    id?: string
}

export interface HumanMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Human
    content: string
    ui_context?: MaxUIContext
}

export interface AssistantFormOption {
    value: string
    variant?: string
}

export interface AssistantForm {
    options: AssistantFormOption[]
}

export interface AssistantMessageMetadata {
    form?: AssistantForm
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
    type: AssistantMessageType.Reasoning
    content: string
    substeps?: string[]
}

/**
 * The union type with all cleaned queries for the assistant. Only used for generating the schemas with an LLM.
 */
export type AnyAssistantGeneratedQuery =
    | AssistantTrendsQuery
    | AssistantFunnelsQuery
    | AssistantRetentionQuery
    | AssistantHogQLQuery

/**
 * The union type with all supported base queries for the assistant.
 */
export type AnyAssistantSupportedQuery = TrendsQuery | FunnelsQuery | RetentionQuery | HogQLQuery

export interface VisualizationItem {
    /** @default '' */
    query: string
    plan?: string
    answer: AnyAssistantGeneratedQuery | AnyAssistantSupportedQuery
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
    tool_calls?: AssistantToolCall[]
}

export enum PlanningStepStatus {
    Pending = 'pending',
    InProgress = 'in_progress',
    Completed = 'completed',
}

export interface PlanningStep {
    description: string
    status: PlanningStepStatus
}

export interface PlanningMessage extends BaseAssistantMessage {
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
    id: string
    description: string
    prompt: string
    status: TaskExecutionStatus
    artifact_ids?: string[]
    progress_text?: string
}

export interface TaskExecutionMessage extends BaseAssistantMessage {
    type: AssistantMessageType.TaskExecution
    tasks: TaskExecutionItem[]
}

export interface MultiVisualizationMessage extends BaseAssistantMessage {
    type: AssistantMessageType.MultiVisualization
    visualizations: VisualizationItem[]
    commentary?: string
}

export type RootAssistantMessage =
    | VisualizationMessage
    | MultiVisualizationMessage
    | ReasoningMessage
    | AssistantMessage
    | HumanMessage
    | FailureMessage
    | NotebookUpdateMessage
    | PlanningMessage
    | TaskExecutionMessage
    | (AssistantToolCallMessage & Required<Pick<AssistantToolCallMessage, 'ui_payload'>>)

export enum AssistantEventType {
    Status = 'status',
    Message = 'message',
    Conversation = 'conversation',
    Notebook = 'notebook',
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
    visible?: boolean
    content: string
    tool_call_id: string
}

export type AssistantContextualTool =
    | 'search_session_recordings'
    | 'generate_hogql_query'
    | 'fix_hogql_query'
    | 'analyze_user_interviews'
    | 'create_and_query_insight'
    | 'create_hog_transformation_function'
    | 'create_hog_function_filters'
    | 'create_hog_function_inputs'
    | 'create_message_template'
    | 'navigate'
    | 'filter_error_tracking_issues'
    | 'find_error_tracking_impactful_issue_event_list'
    | 'experiment_results_summary'
    | 'create_survey'
    | 'search_docs'
    | 'search_insights'
    | 'session_summarization'

/** Exact possible `urls` keys for the `navigate` tool. */
// Extracted using the following Claude Code prompt, then tweaked manually:
// "
// List every key of objects `frontend/src/products.tsx::productUrls` and `frontend/src/scenes/urls.ts::urls`,
// whose function takes either zero arguments, or only optional arguments. Exclude beta or alpha products.
// Exclude scenes related to signup, login, onboarding, upsell or admin, as well as internal scenes, and ones about uploading files.
// Your only output should be a list of those string keys in TypeScript union syntax.
// Once done, verify whether indeed each item of the output satisfies the criteria.
// "
export type AssistantNavigateUrls =
    | 'createAction'
    | 'actions'
    | 'cohorts'
    | 'projectHomepage'
    | 'max'
    | 'settings'
    | 'eventDefinitions'
    | 'propertyDefinitions'
    | 'database'
    | 'activity'
    | 'ingestionWarnings'
    | 'insights'
    | 'insightNew'
    | 'savedInsights'
    | 'webAnalytics'
    | 'webAnalyticsWebVitals'
    | 'alerts'
    | 'dashboards'
    | 'experiments'
    | 'featureFlags'
    | 'surveys'
    | 'surveyTemplates'
    | 'replay'
    | 'replaySettings'
    | 'pipeline'
    | 'sqlEditor'
    | 'annotations'
    | 'heatmaps'
    | 'earlyAccessFeatures'
    | 'errorTracking'
    | 'game368hedgehogs'
    | 'notebooks'
    | 'persons'
    | 'toolbarLaunch'
