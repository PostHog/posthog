import { isDataNode, isEventsTableNode, isLegacyQuery, isSavedInsight, Node } from '../nodes'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery'
import { SavedInsightQuery } from '~/queries/nodes/SavedInsightQuery'
import { EventsTableQuery } from '~/queries/nodes/EventsTableQuery'
import { DataNodeQuery } from '~/queries/nodes/DataNodeQuery'

export interface PostHogQueryProps {
    query: Node | string
}
export function PostHogQuery({ query }: PostHogQueryProps): JSX.Element {
    if (typeof query === 'string') {
        try {
            return <PostHogQuery query={JSON.parse(query)} />
        } catch (e: any) {
            return <div className="border border-danger p-4 text-danger">Error parsing JSON: {e.message}</div>
        }
    }
    if (isLegacyQuery(query)) {
        return <LegacyInsightQuery query={query} />
    } else if (isSavedInsight(query)) {
        return <SavedInsightQuery query={query} />
    } else if (isEventsTableNode(query)) {
        return <EventsTableQuery query={query} />
    } else if (isDataNode(query)) {
        return <DataNodeQuery query={query} />
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong>{' '}
            {query?.nodeType ? `Invalid node type "${query.nodeType}"` : 'Invalid query'}
        </div>
    )
}
