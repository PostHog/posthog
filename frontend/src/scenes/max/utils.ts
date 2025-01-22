import {
    AssistantMessage,
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    ReasoningMessage,
    RootAssistantMessage,
    RouterMessage,
    VisualizationMessage,
} from '~/queries/schema/schema-assistant-messages'
import {
    AssistantFunnelsQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from '~/queries/schema/schema-assistant-queries'
import { FunnelsQuery, RetentionQuery, TrendsQuery } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isRetentionQuery, isTrendsQuery } from '~/queries/utils'

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
export function castAssistantQuery(
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery
): TrendsQuery | FunnelsQuery | RetentionQuery {
    if (isTrendsQuery(query)) {
        return castAssistantTrendsQuery(query)
    } else if (isFunnelsQuery(query)) {
        return castAssistantFunnelsQuery(query)
    } else if (isRetentionQuery(query)) {
        return castAssistantRetentionQuery(query)
    }
    throw new Error('Unsupported query type')
}
