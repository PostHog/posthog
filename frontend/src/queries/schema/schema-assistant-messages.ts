import { AssistantFunnelsQuery, AssistantRetentionQuery, AssistantTrendsQuery } from './schema-assistant-queries'

export enum AssistantMessageType {
    Human = 'human',
    Assistant = 'ai',
    Reasoning = 'ai/reasoning',
    Visualization = 'ai/viz',
    Failure = 'ai/failure',
    Router = 'ai/router',
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

export interface AssistantMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Assistant
    content: string
    meta?: AssistantMessageMetadata
}

export interface ReasoningMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Reasoning
    content: string
    substeps?: string[]
}

export interface VisualizationMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Visualization
    plan?: string
    answer?: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery
    initiator?: string
}

export interface FailureMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Failure
    content?: string
}

export interface RouterMessage extends BaseAssistantMessage {
    type: AssistantMessageType.Router
    content: string
}

export type RootAssistantMessage =
    | VisualizationMessage
    | ReasoningMessage
    | AssistantMessage
    | HumanMessage
    | FailureMessage
    | RouterMessage

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
