import { isEventsNode, isLegacyQuery, isSavedInsight, Node } from '../nodes'
import { LegacyInsightQuery } from '~/queries/PostHogQuery/nodes/LegacyInsightQuery'
import { SavedInsightQuery } from '~/queries/PostHogQuery/nodes/SavedInsightQuery'
import { EventsNodeQuery } from '~/queries/PostHogQuery/nodes/EventsNodeQuery'

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
    } else if (isEventsNode(query)) {
        return <EventsNodeQuery query={query} />
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong>{' '}
            {query?.nodeType ? `Invalid node type "${query.nodeType}"` : 'Invalid query'}
        </div>
    )
}
