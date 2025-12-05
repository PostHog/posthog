// Agent Artifact Types - these will be auto-generated to Python via pnpm schema:build
import { VisualizationArtifactContent } from './schema-assistant-messages'

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

// Re-export for convenience
export type { VisualizationArtifactContent }

export type AgentArtifactContent = DocumentArtifactContent | VisualizationArtifactContent
