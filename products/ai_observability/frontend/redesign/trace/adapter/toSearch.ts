import type { TraceSearchMatchApi, TraceSearchResultsApi } from '../../../generated/api.schemas'
import type { TraceSearchBoxData } from '../components/TraceSearchBox'
import type { MatchDirection, TraceSearchFailure, TraceSearchStatus } from '../types'

export function toMatchingNodeIds(results: TraceSearchResultsApi | null): ReadonlySet<string> | null {
    return results ? new Set(results.matches.map((match) => match.nodeId)) : null
}

/** `selectedNodeId` is null when the current mode does not show the selected step, so stepping starts at an end. */
export function steppedMatchId(
    matches: TraceSearchMatchApi[],
    selectedNodeId: string | null,
    direction: MatchDirection
): string | null {
    if (matches.length === 0) {
        return null
    }
    const index = matches.findIndex((match) => match.nodeId === selectedNodeId)
    if (index === -1) {
        return direction === 'next' ? matches[0].nodeId : matches[matches.length - 1].nodeId
    }
    const step = direction === 'next' ? 1 : -1
    return matches[(index + step + matches.length) % matches.length].nodeId
}

export function toSearchBox(
    query: string,
    status: TraceSearchStatus,
    results: TraceSearchResultsApi | null,
    failure: TraceSearchFailure | null,
    selectedNodeId: string | null
): TraceSearchBoxData {
    const matches = results?.matches ?? []
    const index = matches.findIndex((match) => match.nodeId === selectedNodeId)
    return {
        query,
        status,
        total: results?.total ?? 0,
        matchingSteps: matches.length,
        position: index === -1 ? null : index + 1,
        failure,
    }
}
