import {
    AssistantMessagePayload,
    AssistantMessageType,
    ExperimentalAITrendsQuery,
    VisualizationMessagePayload,
} from '~/queries/schema'

export function isVisualizationMessage(
    payload: AssistantMessagePayload | undefined | null
): payload is VisualizationMessagePayload {
    return !!payload && payload.type === AssistantMessageType.Visualization
}

export interface VisualizationMessageContent {
    reasoning_steps?: string[]
    answer?: ExperimentalAITrendsQuery
}

export function parseVisualizationMessageContent(content: string): VisualizationMessageContent {
    return JSON.parse(content)
}
