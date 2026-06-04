import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'

import type { generationTagRunsLogicType } from './generationTagRunsLogicType'
import { TagRun } from './tags/llmTaggerLogic'

export interface GenerationTagRunsLogicProps {
    generationEventId: string
}

// Shared by the trace tags tab (this loader) and the event-panel TagDisplay so
// the JSON-string defense lives in one place — see TagDisplay.tsx.
export function parseTagsCell(raw: unknown): string[] {
    if (Array.isArray(raw)) {
        return raw as string[]
    }
    if (typeof raw !== 'string') {
        return []
    }
    try {
        const parsed = JSON.parse(raw)
        return Array.isArray(parsed) ? parsed : []
    } catch {
        // One malformed tags cell shouldn't discard the whole result set —
        // just drop this row's tags and keep everything else.
        return []
    }
}

export const generationTagRunsLogic = kea<generationTagRunsLogicType>([
    path(['products', 'llm_analytics', 'frontend', 'generationTagRunsLogic']),
    props({} as GenerationTagRunsLogicProps),
    key((props) => props.generationEventId),

    loaders(({ props }) => ({
        generationTagRuns: [
            [] as TagRun[],
            {
                loadGenerationTagRuns: async () => {
                    // Bind the event id as a HogQL parameter instead of interpolating the
                    // prop into the query string — the id is ultimately URL-derived and
                    // must not be concatenated into HogQL.
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: `
                            SELECT
                                uuid,
                                timestamp,
                                properties.$ai_tags as tags,
                                properties.$ai_tag_reasoning as reasoning,
                                properties.$ai_trace_id as trace_id,
                                properties.$ai_target_event_id as target_event_id,
                                properties.$ai_tagger_id as tagger_id,
                                properties.$ai_tagger_name as tagger_name
                            FROM events
                            WHERE event = '$ai_tag'
                              AND properties.$ai_target_event_id = {generation_event_id}
                            ORDER BY timestamp DESC
                            LIMIT 50
                        `,
                        values: { generation_event_id: props.generationEventId },
                    }
                    // Let kea-loaders surface failures: a swallowed catch here would render
                    // empty-state for both "no tags" and "query broke", masking real errors.
                    const response = await api.query(query)
                    return (response.results || []).map((row: any[]) => ({
                        uuid: row[0],
                        timestamp: row[1],
                        tags: parseTagsCell(row[2]),
                        reasoning: row[3] || '',
                        trace_id: row[4] || '',
                        target_event_id: row[5] || '',
                        tagger_id: row[6] || '',
                        tagger_name: row[7] || '',
                    }))
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadGenerationTagRuns()
    }),
])
