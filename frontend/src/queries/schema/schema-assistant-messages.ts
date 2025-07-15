import type { MaxUIContext } from 'scenes/max/maxTypes'

import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from './schema-assistant-queries'

export enum AssistantMessageType {
    Human = 'human',
    ToolCall = 'tool',
    Assistant = 'ai',
    Reasoning = 'ai/reasoning',
    Visualization = 'ai/viz',
    Failure = 'ai/failure',
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

export interface VisualizationMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Visualization
    /** @default '' */
    query: string
    plan?: string
    answer: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
    initiator?: string
}

export interface FailureMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Failure
    content?: string
}

export type RootAssistantMessage =
    | VisualizationMessage
    | ReasoningMessage
    | AssistantMessage
    | HumanMessage
    | FailureMessage
    | (AssistantToolCallMessage & Required<Pick<AssistantToolCallMessage, 'ui_payload'>>)

export enum AssistantEventType {
    Status = 'status',
    Message = 'message',
    Conversation = 'conversation',
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
    | 'navigate'
    | 'search_error_tracking_issues'

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
