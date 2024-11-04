import {
    AssistantMessageType,
    FailureMessage,
    HumanMessage,
    RootAssistantMessage,
    RouterMessage,
    VisualizationMessage,
} from '~/queries/schema'

export function isVisualizationMessage(
    message: RootAssistantMessage | undefined | null
): message is VisualizationMessage {
    return message?.type === AssistantMessageType.Visualization
}

export function isHumanMessage(message: RootAssistantMessage | undefined | null): message is HumanMessage {
    return message?.type === AssistantMessageType.Human
}

export function isFailureMessage(message: RootAssistantMessage | undefined | null): message is FailureMessage {
    return message?.type === AssistantMessageType.Failure
}

export function isRouterMessage(message: RootAssistantMessage | undefined | null): message is RouterMessage {
    return message?.type === AssistantMessageType.Router
}
