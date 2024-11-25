import {
    AssistantFunnelsQuery,
    AssistantMessage,
    AssistantMessageType,
    AssistantTrendsQuery,
    FailureMessage,
    FunnelsQuery,
    HumanMessage,
    ReasoningMessage,
    RootAssistantMessage,
    RouterMessage,
    TrendsQuery,
    VisualizationMessage,
} from '~/queries/schema'
import { isTrendsQuery } from '~/queries/utils'

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

export function isFailureMessage(message: RootAssistantMessage | undefined | null): message is FailureMessage {
    return message?.type === AssistantMessageType.Failure
}

export function isRouterMessage(message: RootAssistantMessage | undefined | null): message is RouterMessage {
    return message?.type === AssistantMessageType.Router
}

// Both schemas below must infer correct types, so the assistant queries can be converted to a regular query.
/**
 * Type cast for the assistant's trends query.
 */
export function castAssistantTrendsQuery(query: AssistantTrendsQuery): TrendsQuery {
    return query
}

/**
 * Type cast for the assistant's funnels query.
 */
export function castAssistantFunnelsQuery(query: AssistantFunnelsQuery): FunnelsQuery {
    return query
}

export function castAssistantQuery(query: AssistantTrendsQuery | AssistantFunnelsQuery): TrendsQuery | FunnelsQuery {
    if (isTrendsQuery(query)) {
        return castAssistantTrendsQuery(query)
    }

    return castAssistantFunnelsQuery(query as AssistantFunnelsQuery)
}
