import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

import { VisualizationBlock } from '~/queries/schema/schema-assistant-artifacts'
import {
    AgentMode,
    AnyAssistantGeneratedQuery,
    ArtifactContent,
    ArtifactContentType,
    ArtifactMessage,
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    AssistantUpdateEvent,
    FailureMessage,
    HumanMessage,
    MultiVisualizationMessage,
    NotebookArtifactContent,
    NotebookUpdateMessage,
    RootAssistantMessage,
    SubagentUpdateEvent,
    VisualizationArtifactContent,
    VisualizationItem,
} from '~/queries/schema/schema-assistant-messages'
import {
    DashboardFilter,
    DataVisualizationNode,
    HogQLVariable,
    InsightVizNode,
    NodeKind,
    QuerySchema,
    QuerySchemaRoot,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { ActionType, DashboardType, EventDefinition, QueryBasedInsightModel } from '~/types'

import { Scene } from '../sceneTypes'
import { EnhancedToolCall } from './Thread'
import { MODE_DEFINITIONS } from './max-constants'
import { SuggestionGroup } from './maxLogic'
import { MaxActionContext, MaxContextType, MaxDashboardContext, MaxEventContext, MaxInsightContext } from './maxTypes'

export function isMultiVisualizationMessage(
    message: RootAssistantMessage | undefined | null
): message is MultiVisualizationMessage {
    return message?.type === AssistantMessageType.MultiVisualization
}

export function isArtifactMessage(message: RootAssistantMessage | undefined | null): message is ArtifactMessage {
    return message?.type === AssistantMessageType.Artifact
}

export function isVisualizationArtifactContent(content: ArtifactContent): content is VisualizationArtifactContent {
    return content.content_type === ArtifactContentType.Visualization
}

export function isNotebookArtifactContent(content: ArtifactContent): content is NotebookArtifactContent {
    return content.content_type === ArtifactContentType.Notebook
}

export function isHumanMessage(message: RootAssistantMessage | undefined | null): message is HumanMessage {
    return message?.type === AssistantMessageType.Human
}

export function isAssistantMessage(message: RootAssistantMessage | undefined | null): message is AssistantMessage {
    return message?.type === AssistantMessageType.Assistant
}

export function isAssistantToolCallMessage(
    message: RootAssistantMessage | undefined | null
): message is AssistantToolCallMessage & Required<Pick<AssistantToolCallMessage, 'ui_payload'>> {
    return message?.type === AssistantMessageType.ToolCall && message.ui_payload !== undefined
}

export function isSubagentUpdateEvent(
    message: AssistantUpdateEvent | SubagentUpdateEvent | undefined | null
): message is SubagentUpdateEvent {
    return message?.content instanceof Object && 'type' in message.content && message.content.type === 'tool_call'
}

export function isFailureMessage(message: RootAssistantMessage | undefined | null): message is FailureMessage {
    return message?.type === AssistantMessageType.Failure
}

export function isNotebookUpdateMessage(
    message: RootAssistantMessage | undefined | null
): message is NotebookUpdateMessage {
    return message?.type === AssistantMessageType.Notebook
}

export function isMultiQuestionFormMessage(
    message: RootAssistantMessage | undefined | null
): message is AssistantMessage & { tool_calls: EnhancedToolCall[] } {
    return (
        isAssistantMessage(message) &&
        !!message.tool_calls &&
        message.tool_calls.some((toolCall) => toolCall.name === 'create_form')
    )
}

export function threadEndsWithMultiQuestionForm(messages: RootAssistantMessage[]): boolean {
    if (messages.length < 1) {
        return false
    }
    const lastMessage = messages[messages.length - 1]

    // The form is waiting for user input when the last message is an AssistantMessage with a create_form tool call.
    // The create_form tool raises NodeInterrupt(None) which doesn't produce any message, so the thread
    // ends with the AssistantMessage containing the tool call.
    if (isMultiQuestionFormMessage(lastMessage)) {
        return true
    }

    return false
}

export function castAssistantQuery(query: AnyAssistantGeneratedQuery | QuerySchemaRoot | null): QuerySchemaRoot | null {
    if (query) {
        return query as QuerySchemaRoot
    }
    return null
}

export function formatConversationDate(updatedAt: string | null): string {
    if (!updatedAt) {
        return 'Some time ago'
    }

    const diff = dayjs().diff(dayjs(updatedAt), 'seconds')
    if (diff < 60) {
        return 'Just now'
    }
    return humanFriendlyDuration(diff, { maxUnits: 1 })
}

export function getSlackThreadUrl(slackThreadKey: string, slackWorkspaceDomain?: string | null): string {
    const [_, channel, threadTs] = slackThreadKey.split(':')
    // threadTs is like "1765374935.148729", URL needs "p1765374935148729"
    const urlTs = `p${threadTs.replace('.', '')}`
    const domain = slackWorkspaceDomain || 'slack'
    return `https://${domain}.slack.com/archives/${channel}/${urlTs}`
}

/**
 * Checks if a suggestion requires user input.
 * @param suggestion - The suggestion to check.
 * @returns True if the suggestion requires input, false otherwise.
 */
export function checkSuggestionRequiresUserInput(suggestion: string): boolean {
    const matches = suggestion.match(/<|>|…/g)
    return !!matches && matches.length > 0
}

/**
 * Strips the user input placeholder (`<`, `>`, `…`) from a suggestion.
 * @param suggestion - The suggestion to strip.
 * @returns The stripped suggestion.
 */
export function stripSuggestionPlaceholders(suggestion: string): string {
    return `${suggestion
        .replace(/<[^>]*>/g, '')
        .replace(/…$/, '')
        .trim()} `
}

/**
 * Formats a suggestion by stripping the placeholder characters (`<`, `>`) from a suggestion.
 * @param suggestion - The suggestion to format.
 * @returns The formatted suggestion.
 */
export function formatSuggestion(suggestion: string): string {
    return `${suggestion.replace(/[<>]/g, '').replace(/…$/, '').trim()}${suggestion.endsWith('…') ? '…' : ''}`
}

export function isDeepResearchReportNotebook(
    notebook: { category?: string | null; notebook_type?: string | null } | null | undefined
): boolean {
    return !!(notebook && notebook.category === 'deep_research' && notebook.notebook_type === 'report')
}

export function isDeepResearchReportCompletion(message: NotebookUpdateMessage): boolean {
    return (
        message.notebook_type === 'deep_research' &&
        Array.isArray(message.conversation_notebooks) &&
        message.conversation_notebooks.some((nb) => isDeepResearchReportNotebook(nb))
    )
}

// Utility functions for transforming data to max context
export const insightToMaxContext = (
    insight: Partial<QueryBasedInsightModel>,
    filtersOverride?: DashboardFilter,
    variablesOverride?: Record<string, HogQLVariable>
): MaxInsightContext => {
    // Some insights (especially revenue analytics insights) don't have an inner source so we fallback to the outer query
    const source = (insight.query as any)?.source ?? insight.query

    return {
        type: MaxContextType.INSIGHT,
        id: insight.short_id!,
        name: insight.name || insight.derived_name,
        description: insight.description,
        query: source,
        filtersOverride,
        variablesOverride,
    }
}

export const dashboardToMaxContext = (dashboard: DashboardType<QueryBasedInsightModel>): MaxDashboardContext => {
    return {
        type: MaxContextType.DASHBOARD,
        id: dashboard.id,
        name: dashboard.name,
        description: dashboard.description,
        insights: dashboard.tiles.filter((tile) => tile.insight).map((tile) => insightToMaxContext(tile.insight!)),
        filters: dashboard.filters,
    }
}

export const eventToMaxContextPayload = (event: EventDefinition): MaxEventContext => {
    return {
        type: MaxContextType.EVENT,
        id: event.id,
        name: event.name,
        description: event.description,
    }
}

export const actionToMaxContextPayload = (action: ActionType): MaxActionContext => {
    return {
        type: MaxContextType.ACTION,
        id: action.id,
        name: action.name || `Action ${action.id}`,
        description: action.description || '',
    }
}

export const createSuggestionGroup = (label: string, icon: JSX.Element, suggestions: string[]): SuggestionGroup => {
    return {
        label,
        icon,
        suggestions: suggestions.map((content) => ({ content })),
    }
}

export type FeedbackRating = 'bad' | 'okay' | 'good' | 'dismissed' | 'implicit_dismiss'
export type FeedbackTriggerType = 'message_interval' | 'random_sample' | 'manual' | 'retry' | 'cancel'

export function captureFeedback(
    conversationId: string,
    traceId: string | null,
    rating: FeedbackRating,
    triggerType: FeedbackTriggerType,
    feedbackText?: string
): void {
    posthog.capture('$ai_metric', {
        $ai_metric_name: 'feedback',
        $ai_metric_value: rating,
        $ai_session_id: conversationId,
        $ai_trace_id: traceId,
        feedback_trigger_type: triggerType,
    })

    if (feedbackText) {
        posthog.capture('$ai_feedback', {
            $ai_feedback_text: feedbackText,
            $ai_session_id: conversationId,
            $ai_trace_id: traceId,
        })
    }
}

/** Maps a scene ID to the agent mode that should be activated for that scene */
export function getAgentModeForScene(sceneId: Scene | null): AgentMode | null {
    if (!sceneId) {
        return null
    }
    for (const [mode, def] of Object.entries(MODE_DEFINITIONS)) {
        if (def.scenes.has(sceneId)) {
            return mode as AgentMode
        }
    }
    return null
}

export const visualizationTypeToQuery = (
    visualization: VisualizationItem | VisualizationArtifactContent | VisualizationBlock
): QuerySchema | null => {
    const source = castAssistantQuery('answer' in visualization ? visualization.answer : visualization.query)
    if (isHogQLQuery(source)) {
        return { kind: NodeKind.DataVisualizationNode, source: source } satisfies DataVisualizationNode
    }
    if (isInsightQueryNode(source)) {
        return { kind: NodeKind.InsightVizNode, source, showHeader: true } satisfies InsightVizNode
    }
    return source
}
