import { DEFAULT_UNIVERSAL_GROUP_FILTER } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import {
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessageType,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { AssistantRecordingsQueryPropertyFilter } from '~/queries/schema/schema-assistant-queries'
import { RecordingUniversalFilters, UniversalFiltersGroup, UniversalFilterValue } from '~/types'

import type { McpToolCallMessage } from '../../maxTypes'
import { SessionSummarizationUpdate } from '../SessionSummarizationProgress'

/**
 * Shared, pure prop-extractors for the single-exec tool renderer adapters. Each adapter
 * pulls its props out of `message.rawInput` / `message.innerInput` / `message.content` /
 * `message.rawOutput` here and delegates to an existing renderer, untouched. Keeping the
 * shape mapping in one place keeps the adapters thin (5–15 lines).
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §3.3.
 */

/** Narrow an unknown value to a plain object. */
export function asObject(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

/** Prefer the parsed `innerInput` (single-exec JSON body) but fall back to `rawInput`. */
export function toolInput(message: McpToolCallMessage): Record<string, unknown> {
    return message.innerInput ?? message.rawInput ?? {}
}

/** Whether the tool call has reached a terminal completed state. */
export function isCompleted(message: McpToolCallMessage): boolean {
    return message.status === 'completed'
}

/**
 * Concatenate the text of every `{ type: 'text', text }` ACP content frame, joined with
 * newlines. Non-text frames are dropped (the fallback card renders them when needed).
 */
export function extractContentText(content: unknown[] | undefined): string {
    if (!content) {
        return ''
    }
    const parts: string[] = []
    for (const block of content) {
        const obj = asObject(block)
        if (obj && obj.type === 'text' && typeof obj.text === 'string') {
            parts.push(obj.text)
        }
    }
    return parts.join('\n')
}

export interface VisualizationArtifact {
    envelope: ArtifactMessage
    content: VisualizationArtifactContent
}

/**
 * Build a `VisualizationArtifactContent` + `ArtifactMessage` envelope for the insight /
 * typed-query tools. The query comes from the tool input (`query` / `derived_from_query`);
 * `artifact_id` discriminates a saved insight (`source: Insight`) from an ephemeral query
 * (`source: State`). Returns `null` when no query is present.
 */
export function extractVisualizationArtifact(
    message: McpToolCallMessage,
    queryKeys: string[] = ['query', 'derived_from_query', 'source']
): VisualizationArtifact | null {
    const input = toolInput(message)
    let query: unknown
    for (const key of queryKeys) {
        if (input[key] !== undefined && input[key] !== null) {
            query = input[key]
            break
        }
    }
    if (!query || typeof query !== 'object') {
        return null
    }

    const out = asObject(message.rawOutput)
    const artifactId =
        (typeof out?.short_id === 'string' && out.short_id) ||
        (typeof out?.id === 'string' && out.id) ||
        (typeof input.id === 'string' && input.id) ||
        null

    const name =
        (typeof input.name === 'string' && input.name) || (typeof out?.name === 'string' && out.name) || undefined

    const content: VisualizationArtifactContent = {
        content_type: ArtifactContentType.Visualization,
        query: query as VisualizationArtifactContent['query'],
        name: name ?? null,
    }

    const envelope: ArtifactMessage = {
        type: AssistantMessageType.Artifact,
        id: message.id,
        // A saved artifact has an id from the create/update output; an ephemeral query does not.
        artifact_id: artifactId ?? '',
        source: artifactId ? ArtifactSource.Insight : ArtifactSource.State,
        content,
    }

    return { envelope, content }
}

/**
 * Build a fully-typed `RecordingUniversalFilters` for the recordings widget from the flat
 * `AssistantRecordingsQuery` tool input. The single-exec tool `query-session-recordings-list`
 * takes a flat body (`date_from`, `date_to`, `properties`, `filter_test_accounts`, …) and RETURNS
 * a recordings-metadata list (`{ results: [...] }`) — neither side carries a `filter_group` or a
 * `duration`, both of which `RecordingUniversalFilters` requires. The widget's
 * `sessionRecordingsPlaylistLogic` dereferences `filter_group.values` unconditionally, so we must
 * seed those defaults here rather than hand over a partial object. A caller may also nest a
 * ready-made `filters` object; in that case we trust it verbatim. Returns `null` only when there
 * is nothing to render.
 */
export function extractRecordingFilters(message: McpToolCallMessage): RecordingUniversalFilters | null {
    const input = toolInput(message)
    const candidate = Object.keys(input).length > 0 ? input : asObject(asObject(message.rawOutput)?.filters)
    if (!candidate || Object.keys(candidate).length === 0) {
        return null
    }

    return {
        date_from: typeof candidate.date_from === 'string' ? candidate.date_from : null,
        date_to: typeof candidate.date_to === 'string' ? candidate.date_to : null,
        filter_test_accounts:
            typeof candidate.filter_test_accounts === 'boolean' ? candidate.filter_test_accounts : undefined,
        // The flat input never carries a `duration`; seed the widget's default so the playlist logic
        // has a usable array.
        duration: [defaultRecordingDurationFilter],
        filter_group: resolveFilterGroup(candidate),
    }
}

/**
 * Resolve the `filter_group` for the recordings widget. Honors a caller-nested, already-built
 * `filter_group` verbatim; otherwise starts from `DEFAULT_UNIVERSAL_GROUP_FILTER` and folds the
 * flat `AssistantRecordingsQuery` `properties` array into its nested values bucket. Always returns
 * a defined group so `sessionRecordingsPlaylistLogic` can dereference `.type` / `.values` safely.
 */
function resolveFilterGroup(candidate: Record<string, unknown>): UniversalFiltersGroup {
    const provided = asObject(candidate.filter_group)
    if (provided && typeof provided.type === 'string' && Array.isArray(provided.values)) {
        return { type: provided.type as UniversalFiltersGroup['type'], values: provided.values }
    }

    // Deep-copy the default so we never mutate the shared constant.
    const filterGroup: UniversalFiltersGroup = {
        type: DEFAULT_UNIVERSAL_GROUP_FILTER.type,
        values: DEFAULT_UNIVERSAL_GROUP_FILTER.values.map((group) =>
            typeof group === 'object' && group !== null && 'values' in group
                ? { ...group, values: [...group.values] }
                : group
        ),
    }

    const properties = Array.isArray(candidate.properties)
        ? (candidate.properties as AssistantRecordingsQueryPropertyFilter[])
        : []
    if (properties.length === 0) {
        return filterGroup
    }

    // The Assistant filters are structurally property filters (type/key/value/operator) over a
    // narrower enum, so they slot into the universal group as `UniversalFilterValue`s.
    const universalValues = properties.map((property) => property as UniversalFilterValue)
    const innerGroup = filterGroup.values.find(
        (group): group is UniversalFiltersGroup => typeof group === 'object' && group !== null && 'values' in group
    )
    if (innerGroup) {
        innerGroup.values.push(...universalValues)
    } else {
        filterGroup.values.push(...universalValues)
    }
    return filterGroup
}

export interface SummarizeSessionsPayload {
    session_group_summary_id?: string
    title?: string
}

/** Final payload for the summarize-sessions CTA, read off `rawOutput` on completion. */
export function extractSummarizePayload(message: McpToolCallMessage): SummarizeSessionsPayload | null {
    if (!isCompleted(message)) {
        return null
    }
    const out = asObject(message.rawOutput)
    if (!out) {
        return null
    }
    return {
        session_group_summary_id:
            typeof out.session_group_summary_id === 'string' ? out.session_group_summary_id : undefined,
        title: typeof out.title === 'string' ? out.title : undefined,
    }
}

/**
 * Walk the streamed `content[]` text frames and collect the ones that parse to a
 * `SessionSummarizationUpdate` (`{ type: 'sessions_discovered' | 'progress', … }`). The
 * adapter owns this streaming shape so `SessionSummarizationProgress` stays unchanged.
 */
export function parseSessionSummarizationUpdates(content: unknown[] | undefined): SessionSummarizationUpdate[] {
    if (!content) {
        return []
    }
    const updates: SessionSummarizationUpdate[] = []
    for (const block of content) {
        const obj = asObject(block)
        if (!obj || obj.type !== 'text' || typeof obj.text !== 'string') {
            continue
        }
        try {
            const parsed = JSON.parse(obj.text) as { type?: unknown }
            if (parsed.type === 'sessions_discovered' || parsed.type === 'progress') {
                updates.push(parsed as SessionSummarizationUpdate)
            }
        } catch {
            // Not a JSON update frame — ignore.
        }
    }
    return updates
}

/** Header text for the single-exec discovery verbs, derived from the raw `command`. */
export function extractExecVerbHeader(message: McpToolCallMessage): string {
    const command = typeof message.rawInput?.command === 'string' ? message.rawInput.command.trim() : ''
    const match = command.match(/^(tools|search|info|schema)(?:\s+([\s\S]*))?$/)
    if (!match) {
        return 'PostHog tools'
    }
    const arg = (match[2] ?? '').trim()
    switch (match[1]) {
        case 'tools':
            return 'List tools'
        case 'search':
            return arg ? `Search tools ${arg}` : 'Search tools'
        case 'info':
            return arg ? `Read ${arg}` : 'Read tool'
        case 'schema':
            return arg ? `Inspect ${arg}` : 'Inspect schema'
        default:
            return 'PostHog tools'
    }
}
