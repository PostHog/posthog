import { recordingsQueryToUniversalFilters } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'
import {
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessageType,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters } from '~/types'

import type { McpToolCallMessage } from '../../maxTypes'

/**
 * Shared shape extractors for the sandbox MCP tool renderer adapters. Each turns a flattened
 * `McpToolCallMessage` (built by `sandboxStreamLogic` from ACP frames) into the props the existing
 * `messages/*` renderer components already expect, so those components stay untouched.
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
 * server returns the artifact directly in the existing schema shape. Saved insights
 * (create / update / get) carry a `short_id` in the REST payload (or an explicit `artifact_id`);
 * query-only outputs carry neither and render inline as ephemeral visualizations.
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
    const isSaved = asString(output.short_id) !== undefined || asString(output.artifact_id) !== undefined
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

/** Dashboard create/update output — the REST payload (`id`, `name`) plus the MCP server's `_posthogUrl` enrichment. */
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
    const id = (output.id ?? output.dashboard_id) as string | number | undefined
    return {
        id,
        name: asString(output.name) ?? asString(message.innerInput?.name),
        url: asString(output._posthogUrl) ?? asString(output.url),
    }
}

/**
 * Resolves the `RecordingUniversalFilters` the playlist widget renders. The query-wrapper tool
 * echoes the executed `RecordingsQuery` back under `rawOutput.query`, which we convert; a
 * ready-made universal filters object under `rawOutput.filters` is passed through. Anything else
 * falls back to the generic card rather than feeding the playlist a shape it can't use.
 */
export function extractRecordingFilters(message: McpToolCallMessage): RecordingUniversalFilters | null {
    const output = asRecord(message.rawOutput)
    if (!output) {
        return null
    }

    const directFilters = asRecord(output.filters)
    if (directFilters && 'filter_group' in directFilters && Array.isArray(directFilters.duration)) {
        return directFilters as unknown as RecordingUniversalFilters
    }

    const query = asRecord(output.query)
    if (query && query.kind === NodeKind.RecordingsQuery) {
        const recordingsQuery = query as unknown as RecordingsQuery
        // The shared converter intentionally drops list-level fields (its caller manages them
        // separately) — carry them over so the widget reflects what the agent actually searched.
        return {
            ...recordingsQueryToUniversalFilters(recordingsQuery),
            date_from: recordingsQuery.date_from ?? null,
            date_to: recordingsQuery.date_to ?? null,
            order: recordingsQuery.order,
            order_direction: recordingsQuery.order_direction,
            limit: recordingsQuery.limit,
            session_ids: recordingsQuery.session_ids,
        }
    }

    return null
}

const ERROR_TRACKING_RESPONSE_KEYS: readonly (keyof MaxErrorTrackingSearchResponse)[] = [
    'issues',
    'search_query',
    'status',
    'date_from',
    'order_by',
]

/**
 * Error-tracking search output is a `MaxErrorTrackingSearchResponse` (a filters echo plus issue
 * previews) for `ErrorTrackingFiltersWidget`. Outputs that carry none of its fields — e.g. a raw
 * REST issues list — fall back to the generic card instead of rendering empty filter chips.
 */
export function extractErrorTrackingResponse(message: McpToolCallMessage): MaxErrorTrackingSearchResponse | null {
    const output = asRecord(message.rawOutput)
    if (!output || !ERROR_TRACKING_RESPONSE_KEYS.some((key) => key in output)) {
        return null
    }
    return output as MaxErrorTrackingSearchResponse
}
