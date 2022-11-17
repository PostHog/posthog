import { isDataNode, isEventsTableNode, isLegacyQuery, isSavedInsightNode } from '../utils'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery'
import { SavedInsightQuery } from '~/queries/nodes/SavedInsightQuery'
import { EventsTableQuery } from '~/queries/nodes/EventsTableQuery'
import { DataNodeQuery } from '~/queries/nodes/DataNodeQuery'
import { Node } from '~/queries/nodes'

export interface QueryProps {
    query: Node | string
    setQuery?: (node: Node) => void
}

export function Query({ query, setQuery }: QueryProps): JSX.Element {
    if (typeof query === 'string') {
        try {
            return <Query query={JSON.parse(query)} />
        } catch (e: any) {
            return <div className="border border-danger p-4 text-danger">Error parsing JSON: {e.message}</div>
        }
    }
    if (isLegacyQuery(query)) {
        return <LegacyInsightQuery query={query} />
    } else if (isSavedInsightNode(query)) {
        return <SavedInsightQuery query={query} />
    } else if (isEventsTableNode(query)) {
        return <EventsTableQuery query={query} setQuery={setQuery} />
    } else if (isDataNode(query)) {
        return <DataNodeQuery query={query} />
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong> {query?.kind ? `Invalid node type "${query.kind}"` : 'Invalid query'}
        </div>
    )
}
