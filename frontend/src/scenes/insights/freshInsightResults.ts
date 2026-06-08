import { AnyResponseType } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

// One-shot cross-scene handoff of a freshly-computed insight result.
// When the SQL editor saves an insight it already has the computed result in hand, so it
// stashes it here keyed by short id. The insight view consumes it on mount and feeds it to
// the data node as cachedResults, so the view renders fresh immediately without recomputing.
const freshResults = new Map<InsightShortId, AnyResponseType>()

export function stashFreshInsightResult(shortId: InsightShortId, response: AnyResponseType): void {
    freshResults.set(shortId, response)
}

export function consumeFreshInsightResult(shortId: InsightShortId): AnyResponseType | undefined {
    const response = freshResults.get(shortId)
    freshResults.delete(shortId)
    return response
}
