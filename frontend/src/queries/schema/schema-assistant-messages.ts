import { AssistantFunnelsQuery, AssistantRetentionQuery, AssistantTrendsQuery } from './schema-assistant-queries'

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
    answer?: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery
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
    content: string
    tool_call_id: string
}
