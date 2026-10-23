import { useActions } from 'kea'

import { playlistFiltersLogic } from 'scenes/session-recordings/playlist/playlistFiltersLogic'

import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { RecordingUniversalFilters } from '~/types'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import {
    DEFAULT_RECORDING_FILTERS_ORDER_BY,
    DURATION_KEYS,
    isValidRecordingOrder,
    recordingsQueryToUniversalFilters,
} from './recordingsQueryConversions'

// Static instruction rendered into the trusted context block. Never interpolate user or ingested data.
const RECORDINGS_QUERY_TOOL_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The user has the session replay list open. When you call query-session-recordings-list, the filters from ' +
        'your query (properties, duration, date range, ordering) are also applied to the open recordings list, so ' +
        'the user sees matching recordings both in this chat and on screen.',
}

// Recording-metric keys of the query's `properties` filters, whose `type: 'recording'` is a zod
// default the agent may omit from its raw args.
const RECORDING_METRIC_KEYS = new Set([
    ...DURATION_KEYS,
    'console_error_count',
    'console_log_count',
    'console_warn_count',
    'click_count',
    'keypress_count',
    'activity_score',
    'visited_page',
    'snapshot_source',
])

/**
 * Attaches the open list's filters to PostHog AI and mirrors the filters it produces back onto the list, for
 * whichever header holds the filter button.
 */
export function useRecordingFiltersAssist({
    filters,
    setFilters,
    currentSessionRecordingId,
}: {
    filters: RecordingUniversalFilters
    setFilters: (filters: Partial<RecordingUniversalFilters>) => void
    currentSessionRecordingId?: string
}): { applyFilters: (toolOutput: Record<string, any>) => void } {
    const { setIsFiltersExpanded } = useActions(playlistFiltersLogic)
    useAttachedContext([
        { type: 'recording_filters', value: JSON.stringify(filters), label: 'Current filters' },
        RECORDINGS_QUERY_TOOL_CONTEXT_ITEM,
        ...(currentSessionRecordingId
            ? [{ type: 'session_recording', key: currentSessionRecordingId, label: 'Current session' } as const]
            : []),
    ] as AttachedContextItem[])

    const applyFilters = (toolOutput: Record<string, any>): void => {
        // Improve type
        setFilters(toolOutput.recordings_filters)
        setIsFiltersExpanded(true)
    }

    // The headless query tool's call input mirrored onto the open list. The input is a complete query:
    // every field is applied, with omitted fields set to the query schema's defaults so the list shows
    // the same recordings the tool returned. The args are raw agent-sent JSON (never zod-validated), so
    // fields are coerced and the recording-metric `type` default is stamped back on before converting to
    // the universal filter shape. person_uuid (query-level constraint), after (pagination cursor), and
    // limit (the agent's page size, which shouldn't shrink the user's list) have no counterpart in the
    // universal filters.
    const applyRecordingsQuery = (input: Record<string, any>): void => {
        const props = (Array.isArray(input.properties) ? input.properties : []).map((f: Record<string, any>) =>
            f && !f.type && RECORDING_METRIC_KEYS.has(f.key) ? { ...f, type: 'recording' } : f
        )
        // Duration filters have their own control in the universal shape, so the converter expects
        // them in `having_predicates` rather than `properties`.
        const universal = recordingsQueryToUniversalFilters({
            kind: NodeKind.RecordingsQuery,
            properties: props.filter((f: Record<string, any>) => !DURATION_KEYS.has(f?.key)),
            having_predicates: props.filter((f: Record<string, any>) => DURATION_KEYS.has(f?.key)),
        } as RecordingsQuery)
        setFilters({
            filter_group: universal.filter_group,
            duration: universal.duration,
            date_from: input.date_from ?? '-3d',
            date_to: input.date_to ?? null,
            filter_test_accounts: !!input.filter_test_accounts,
            order: isValidRecordingOrder(input.order) ? input.order : DEFAULT_RECORDING_FILTERS_ORDER_BY,
            order_direction: input.order_direction === 'ASC' ? 'ASC' : 'DESC',
            session_ids: Array.isArray(input.session_ids) ? input.session_ids : undefined,
        })
        setIsFiltersExpanded(true)
    }

    useMcpToolApplyBack({
        tools: ['query-session-recordings-list'],
        targetKey: 'replay-playlist-filters',
        onApply: (_event, { innerInput }) => {
            if (!innerInput) {
                return
            }
            applyRecordingsQuery(innerInput)
        },
    })

    return { applyFilters }
}
