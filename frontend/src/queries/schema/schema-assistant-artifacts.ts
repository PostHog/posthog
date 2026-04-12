// Agent Artifact Types - these will be auto-generated to Python via pnpm schema:build
import { AnyAssistantGeneratedQuery } from './schema-assistant-messages'
import {
    FunnelsQuery,
    HogQLQuery,
    RetentionQuery,
    RevenueAnalyticsGrossRevenueQuery,
    RevenueAnalyticsMRRQuery,
    RevenueAnalyticsMetricsQuery,
    RevenueAnalyticsTopCustomersQuery,
    TrendsQuery,
} from './schema-general'

export interface MarkdownBlock {
    type: 'markdown'
    content: string
}

export interface VisualizationBlock {
    type: 'visualization'
    /** The query to render (same as VisualizationArtifactContent.query) */
    query:
        | AnyAssistantGeneratedQuery
        | TrendsQuery
        | FunnelsQuery
        | RetentionQuery
        | HogQLQuery
        | RevenueAnalyticsGrossRevenueQuery
        | RevenueAnalyticsMetricsQuery
        | RevenueAnalyticsMRRQuery
        | RevenueAnalyticsTopCustomersQuery
    /** Optional title for the visualization */
    title?: string | null
}

export interface SessionReplayBlock {
    type: 'session_replay'
    session_id: string
    timestamp_ms: number
    title?: string | null
}

export interface LoadingBlock {
    type: 'loading'
    /** The artifact ID that is being loaded */
    artifact_id: string
}

export interface ErrorBlock {
    type: 'error'
    /** Error message to display */
    message: string
    /** Optional artifact ID if the error is related to a specific artifact */
    artifact_id?: string | null
}

export type DocumentBlock = MarkdownBlock | VisualizationBlock | SessionReplayBlock | LoadingBlock | ErrorBlock

export interface DocumentArtifactContent {
    blocks: DocumentBlock[]
}
