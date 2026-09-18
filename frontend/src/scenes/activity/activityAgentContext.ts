import { DataTableNode, Node } from '~/queries/schema/schema-general'
import { ActivityTab, AnyPropertyFilter } from '~/types'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

// A chip and the hidden instruction it stands for share a dismiss group, so closing the chip also
// detaches the instruction.
const EXPLORE_DISMISS_GROUP = 'activity-explore-query'
const LIVE_DISMISS_GROUP = 'activity-live-filters'

// The legacy Max bridge flattens these items into `text` attachments, and the backend rejects a text
// value over MAX_TEXT_LENGTH (4096) in products/posthog_ai/backend/context_wrapper.py, which fails
// the user's whole message. Stay under that, with room for the surrounding block.
export const CONTEXT_VALUE_MAX_CHARS = 3_500

const ELIDED_MARKER = '[elided for size]'

// The strings below are our own build-time constants, which is what makes them safe to attach as
// trusted `instructions` items. Which tab is open travels on the untrusted item's `type` instead,
// so no value read off the page reaches trusted context.
const EXPLORE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: EXPLORE_DISMISS_GROUP,
    value:
        'The user has the PostHog activity explorer open, which lists raw events and sessions. The ' +
        'events_explorer_query or sessions_explorer_query item is the live, possibly unsaved query behind the ' +
        'table on their screen. Read it to resolve what "this", "these rows", or "the current filters" refer ' +
        'to. Answer questions about it by running HogQL over the events or sessions table with the execute-sql ' +
        'tool. Keep the columns, filters, and time range of that query unless the user asks to change them. ' +
        'A field whose value is "' +
        ELIDED_MARKER +
        '" was too large to send, so ask the user what it holds rather than ' +
        'assuming it is empty. Results you compute are not applied back to the open table, so say so when you ' +
        'answer from a query other than the one on screen.',
}

const LIVE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: LIVE_DISMISS_GROUP,
    value:
        'The user is watching the PostHog live event stream, which shows events as they arrive. The ' +
        'live_events_filters item holds the event name and property filters applied to that stream. The ' +
        'stream itself is not queryable, so answer questions about what the user sees by running HogQL over ' +
        'the events table with the execute-sql tool, applying the same filters over a recent time range.',
}

// `select`, `where`, `properties`, `fixedProperties` and `eventProperties` all grow with what the
// user builds, so no single field can be trusted to stay small. Eliding the heaviest first, only as
// far as the budget needs, keeps the rest. Blind truncation would leave the JSON unparseable.
function serializeBounded(payload: Record<string, unknown>): string {
    const serialized = JSON.stringify(payload)
    if (serialized.length <= CONTEXT_VALUE_MAX_CHARS) {
        return serialized
    }
    const heaviestFirst = Object.keys(payload).sort(
        (a, b) => JSON.stringify(payload[b] ?? null).length - JSON.stringify(payload[a] ?? null).length
    )
    const elided: Record<string, unknown> = { ...payload }
    for (const field of heaviestFirst) {
        // `kind` names the query type in a few characters and is what the agent needs to read the rest.
        if (field === 'kind') {
            continue
        }
        elided[field] = ELIDED_MARKER
        const candidate = JSON.stringify(elided)
        if (candidate.length <= CONTEXT_VALUE_MAX_CHARS) {
            return candidate
        }
    }
    return JSON.stringify({ kind: payload.kind ?? null, elided: ELIDED_MARKER })
}

// The `DataTableNode` wrapper holds display chrome (column configurator toggles, url syncing) that
// costs tokens on every message and tells the agent nothing, so only its source travels.
function serializeExploreQuery(query: Node | DataTableNode): string {
    const source = 'source' in query && query.source ? query.source : query
    return serializeBounded({ ...source })
}

export function buildExploreAgentContext(
    tab: ActivityTab.ExploreEvents | ActivityTab.ExploreSessions,
    query: Node | DataTableNode
): AttachedContextItem[] {
    const isEvents = tab === ActivityTab.ExploreEvents
    return [
        {
            type: isEvents ? 'events_explorer_query' : 'sessions_explorer_query',
            value: serializeExploreQuery(query),
            label: isEvents ? 'Current events query' : 'Current sessions query',
            dismissGroup: EXPLORE_DISMISS_GROUP,
        },
        EXPLORE_CONTEXT_ITEM,
    ]
}

export function buildLiveEventsAgentContext(filters: {
    eventType: string | null
    properties: AnyPropertyFilter[]
}): AttachedContextItem[] {
    return [
        {
            type: 'live_events_filters',
            value: serializeBounded({ ...filters }),
            label: 'Current live filters',
            dismissGroup: LIVE_DISMISS_GROUP,
        },
        LIVE_CONTEXT_ITEM,
    ]
}
