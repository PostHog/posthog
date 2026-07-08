import { afterMount, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'

import { LLMTrace, NodeKind, TraceQuery, TraceQueryResponse } from '~/queries/schema/schema-general'

import type { inboxLlmTraceLogicType } from './inboxLlmTraceLogicType'

export interface InboxLlmTraceLogicProps {
    traceId: string
}

// Earliest timestamp we look back to when fetching a trace by id without a known date — mirrors the
// wide default used by the AI observability trace scene logic. Signals reference older traces, so a
// narrow window would miss them.
const TRACE_LOOKBACK_FLOOR = dayjs.utc(new Date(2025, 0, 10)).toISOString()

/**
 * Keyed loader that eagerly fetches a single `LLMTrace` by id for an inbox signal card. Intentionally
 * standalone — it does not mount the AI observability trace scene logic (which owns URL routing). On
 * failure it returns `null` so the card degrades to text-only rather than blocking.
 */
export const inboxLlmTraceLogic = kea<inboxLlmTraceLogicType>([
    path((key) => ['scenes', 'inbox', 'components', 'signalCards', 'inboxLlmTraceLogic', key]),
    props({} as InboxLlmTraceLogicProps),
    key((props) => props.traceId),

    loaders(({ props }) => ({
        trace: [
            null as LLMTrace | null,
            {
                loadTrace: async () => {
                    if (!props.traceId) {
                        return null
                    }
                    const query: TraceQuery = {
                        kind: NodeKind.TraceQuery,
                        traceId: props.traceId,
                        dateRange: { date_from: TRACE_LOOKBACK_FLOOR },
                    }
                    try {
                        const response = (await api.query(query)) as TraceQueryResponse
                        return response.results[0] ?? null
                    } catch {
                        // Degrade to text-only — never block the card on a fetch failure.
                        return null
                    }
                },
            },
        ],
    })),

    afterMount(({ actions }) => {
        actions.loadTrace()
    }),
])
