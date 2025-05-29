import { decodeParams, encodeParams } from 'kea-router'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDuration } from 'lib/utils'

import {
    AssistantMessage,
    AssistantMessageType,
    AssistantToolCallMessage,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RootAssistantMessage,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import { FunnelsQuery, HogQLQuery, RetentionQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isHogQLQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'
import { SidePanelTab } from '~/types'

export function isReasoningMessage(message: RootAssistantMessage | undefined | null): message is ReasoningMessage {
    return message?.type === AssistantMessageType.Reasoning
}

export function isVisualizationMessage(
    message: RootAssistantMessage | undefined | null
): message is VisualizationMessage {
    return message?.type === AssistantMessageType.Visualization
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

// The cast function below look like no-ops, but they're here to ensure AssistantFooQuery types stay compatible
// with their respective FooQuery types. If an incompatibility arises, TypeScript will shout here
function castAssistantTrendsQuery(query: AssistantTrendsQuery): TrendsQuery {
    return query
}
function castAssistantFunnelsQuery(query: AssistantFunnelsQuery): FunnelsQuery {
    return query
}
function castAssistantRetentionQuery(query: AssistantRetentionQuery): RetentionQuery {
    return query
}
function castAssistantHogQLQuery(query: AssistantHogQLQuery): HogQLQuery {
    return query
}
export function castAssistantQuery(
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
): TrendsQuery | FunnelsQuery | RetentionQuery | HogQLQuery {
    if (isTrendsQuery(query)) {
        return castAssistantTrendsQuery(query)
    } else if (isFunnelsQuery(query)) {
        return castAssistantFunnelsQuery(query)
    } else if (isRetentionQuery(query)) {
        return castAssistantRetentionQuery(query)
    } else if (isHogQLQuery(query)) {
        return castAssistantHogQLQuery(query)
    }
    throw new Error(`Unsupported query type: ${query.kind}`)
}

/**
 * Generate a URL for a conversation.
 */
export function getConversationUrl({
    pathname,
    search,
    conversationId,
    includeHash = true,
}: {
    pathname: string
    search: string
    conversationId: string
    includeHash?: boolean
}): string {
    const params = decodeParams(search, '?')
    const strParams = encodeParams({
        ...params,
        chat: conversationId,
    })
    return `${pathname}${strParams ? `?${strParams}` : ''}${includeHash ? `#panel=${SidePanelTab.Max}` : ''}`
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
