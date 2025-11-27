// Agent Artifact Types - these will be auto-generated to Python via pnpm schema:build
import {
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantTrendsQuery,
} from './schema-assistant-queries'

export interface MarkdownBlock {
    type: 'markdown'
    content: string
}

export interface VisualizationBlock {
    type: 'visualization'
    artifact_id: string
}

export interface SessionReplayBlock {
    type: 'session_replay'
    session_id: string
    timestamp_ms: number
    title?: string | null
}

export type DocumentBlock = MarkdownBlock | VisualizationBlock | SessionReplayBlock

export interface DocumentArtifactContent {
    blocks: DocumentBlock[]
}

export interface VisualizationArtifactContent {
    query: AssistantTrendsQuery | AssistantFunnelsQuery | AssistantRetentionQuery | AssistantHogQLQuery
    name?: string | null
    description?: string | null
}

export type AgentArtifactContent = DocumentArtifactContent | VisualizationArtifactContent
