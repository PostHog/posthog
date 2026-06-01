import { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'
import {
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessageType,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { RecordingUniversalFilters } from '~/types'

import type { McpToolCallMessage } from '../../maxTypes'

/**
 * Shared shape extractors for the sandbox MCP tool renderer adapters. Each turns a flattened
 * `McpToolCallMessage` (built by `sandboxStreamLogic` from ACP frames) into the props the existing
 * `messages/*` renderer components already expect, so those components stay untouched. See
 * docs/internal/posthog-ai-migration/03_RICH_UI.md § 3.3 and MCP_TOOLS.md for the per-tool shapes.
 */

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function asString(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined
}

/** The artifact envelope + content `VisualizationArtifactAnswer` consumes, plus the resolved status. */
export interface VisualizationArtifactExtraction {
    envelope: ArtifactMessage
    content: VisualizationArtifactContent
}

/**
 * Pulls a `VisualizationArtifactContent` out of an insight tool's `rawOutput`. The backend MCP
 * server returns the artifact directly in the existing schema shape (MCP_TOOLS.md `read_insight` /
 * `create_insight`). Saved insights (create/update) carry an `artifact_id` and source `Insight`;
 * ephemeral queries (`insight-query`) carry neither and render inline.
 */
export function extractVisualizationArtifact(message: McpToolCallMessage): VisualizationArtifactExtraction | null {
    const output = asRecord(message.rawOutput)
    if (!output) {
        return null
    }

    const query = output.query
    if (!query) {
        return null
    }

    const artifactId = asString(output.artifact_id) ?? asString(output.short_id) ?? message.id
    const isSaved = output.source === ArtifactSource.Insight || asString(output.artifact_id) !== undefined
    const source = isSaved ? ArtifactSource.Insight : ArtifactSource.State

    const content: VisualizationArtifactContent = {
        content_type: ArtifactContentType.Visualization,
        query: query as VisualizationArtifactContent['query'],
        name: asString(output.name) ?? asString(message.innerInput?.name) ?? null,
        description: asString(output.description) ?? null,
    }

    const envelope: ArtifactMessage = {
        type: AssistantMessageType.Artifact,
        id: message.id,
        artifact_id: artifactId,
        source,
        content,
    }

    return { envelope, content }
}

/** Dashboard create/update output — `{ dashboard_id | id, url, name }`. See MCP_TOOLS.md `upsert_dashboard`. */
export interface DashboardExtraction {
    id?: string | number
    name?: string
    url?: string
}

export function extractDashboard(message: McpToolCallMessage): DashboardExtraction | null {
    const output = asRecord(message.rawOutput)
    if (!output) {
        return null
    }
    const id = (output.dashboard_id ?? output.id) as string | number | undefined
    return {
        id,
        name: asString(output.name) ?? asString(message.innerInput?.name),
        url: asString(output.url),
    }
}

/**
 * Recording-search output carries the resolved `RecordingUniversalFilters` (MCP_TOOLS.md
 * `search_session_recordings`). The widget renders the live playlist from these filters.
 */
export function extractRecordingFilters(message: McpToolCallMessage): RecordingUniversalFilters | null {
    const output = asRecord(message.rawOutput)
    const filters = output?.filters ?? message.rawOutput
    return asRecord(filters) ? (filters as RecordingUniversalFilters) : null
}

/**
 * Error-tracking search output is a `MaxErrorTrackingSearchResponse` directly (MCP_TOOLS.md
 * `search_error_tracking_issues`). Returned as-is for `ErrorTrackingFiltersWidget`.
 */
export function extractErrorTrackingResponse(message: McpToolCallMessage): MaxErrorTrackingSearchResponse | null {
    return asRecord(message.rawOutput) as MaxErrorTrackingSearchResponse | null
}
