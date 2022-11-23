import { isDataNode, isEventsTableNode, isLegacyQuery } from '../utils'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery'
import { EventsTableQuery } from '~/queries/nodes/EventsTableQuery'
import { DataNodeQuery } from '~/queries/nodes/DataNodeQuery'
import { Node } from '~/queries/schema'
import { ErrorBoundary } from '~/layout/ErrorBoundary'

export interface QueryProps {
    query: Node | string
    setQuery?: (node: Node) => void
}

export function Query(props: QueryProps): JSX.Element {
    const { query, setQuery } = props
    if (typeof query === 'string') {
        try {
            return <Query {...props} query={JSON.parse(query)} />
        } catch (e: any) {
            return <div className="border border-danger p-4 text-danger">Error parsing JSON: {e.message}</div>
        }
    }
    let component
    if (isLegacyQuery(query)) {
        component = <LegacyInsightQuery query={query} />
    } else if (isEventsTableNode(query)) {
        component = <EventsTableQuery query={query} setQuery={setQuery} />
    } else if (isDataNode(query)) {
        component = <DataNodeQuery query={query} />
    }

    if (component) {
        return <ErrorBoundary>{component}</ErrorBoundary>
    }

    return (
        <div className="text-danger border border-danger p-2">
            <strong>PostHoqQuery error:</strong> {query?.kind ? `Invalid node type "${query.kind}"` : 'Invalid query'}
        </div>
    )
}
