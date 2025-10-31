import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

import {
    AnyAssistantGeneratedQuery,
    AnyAssistantSupportedQuery,
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    MultiVisualizationMessage,
    NotebookUpdateMessage,
    RootAssistantMessage,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import {
    DashboardFilter,
    FunnelsQuery,
    HogQLQuery,
    HogQLVariable,
    RetentionQuery,
    TrendsQuery,
} from '~/queries/schema/schema-general'
import { isFunnelsQuery, isHogQLQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { ActionType, DashboardType, EventDefinition, QueryBasedInsightModel } from '~/types'

import { SuggestionGroup } from './maxLogic'
import { MaxActionContext, MaxContextType, MaxDashboardContext, MaxEventContext, MaxInsightContext } from './maxTypes'

export function isVisualizationMessage(
    message: RootAssistantMessage | undefined | null
): message is VisualizationMessage {
    return message?.type === AssistantMessageType.Visualization
}

export function isMultiVisualizationMessage(
    message: RootAssistantMessage | undefined | null
): message is MultiVisualizationMessage {
    return message?.type === AssistantMessageType.MultiVisualization
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

export function isFailureMessage(message: RootAssistantMessage | undefined | null): message is FailureMessage {
    return message?.type === AssistantMessageType.Failure
}

export function isNotebookUpdateMessage(
    message: RootAssistantMessage | undefined | null
): message is NotebookUpdateMessage {
    return message?.type === AssistantMessageType.Notebook
}

export function castAssistantQuery(
    query: AnyAssistantGeneratedQuery | AnyAssistantSupportedQuery | null
): TrendsQuery | FunnelsQuery | RetentionQuery | HogQLQuery {
    if (isTrendsQuery(query)) {
        return query
    } else if (isFunnelsQuery(query)) {
        return query
    } else if (isRetentionQuery(query)) {
        return query
    } else if (isHogQLQuery(query)) {
        return query
    }
    throw new Error(`Unsupported query type: ${query?.kind}`)
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

export function generateBurstPoints(spikeCount: number, spikiness: number): string {
    if (spikiness < 0 || spikiness > 1) {
        throw new Error('Spikiness must be between 0 and 1')
    }
    if (spikeCount < 1) {
        throw new Error('Spikes must be at least 1')
    }

    let points = ''
    const outerRadius = 50
    const innerRadius = 50 * (1 - spikiness)

    for (let i = 0; i < spikeCount * 2; i++) {
        const radius = i % 2 === 0 ? outerRadius : innerRadius
        const angle = (Math.PI * i) / spikeCount
        const x = 50 + radius * Math.cos(angle)
        const y = 50 + radius * Math.sin(angle)
        points += `${x},${y} `
    }

    return points.trim()
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
