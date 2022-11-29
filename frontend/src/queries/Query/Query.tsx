import {
    isDataNode,
    isDataTableNode,
    isLegacyQuery,
    isTrendsQuery,
    isFunnelsQuery,
    isRetentionQuery,
    isPathsQuery,
    isStickinessQuery,
    isLifecycleQuery,
} from '../utils'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { Node } from '~/queries/schema'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery/LegacyInsightQuery'
import { TrendsInsightQuery } from '~/queries/nodes/TrendsInsightQuery/TrendsInsightQuery'
import { FunnelsInsightQuery } from '~/queries/nodes/FunnelsInsightQuery/FunnelsInsightQuery'
import { RetentionInsightQuery } from '~/queries/nodes/RetentionInsightQuery/RetentionInsightQuery'
import { PathsInsightQuery } from '~/queries/nodes/PathsInsightQuery/PathsInsightQuery'
import { StickinessInsightQuery } from '~/queries/nodes/StickinessInsightQuery/StickinessInsightQuery'
import { LifecycleInsightQuery } from '~/queries/nodes/LifecycleInsightQuery/LifecycleInsightQuery'

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
    } else if (isDataTableNode(query)) {
        component = <DataTable query={query} setQuery={setQuery} />
    } else if (isDataNode(query)) {
        component = <DataNode query={query} />
    } else if (isTrendsQuery(query)) {
        component = <TrendsInsightQuery query={query} />
    } else if (isFunnelsQuery(query)) {
        component = <FunnelsInsightQuery query={query} />
    } else if (isRetentionQuery(query)) {
        component = <RetentionInsightQuery query={query} />
    } else if (isPathsQuery(query)) {
        component = <PathsInsightQuery query={query} />
    } else if (isStickinessQuery(query)) {
        component = <StickinessInsightQuery query={query} />
    } else if (isLifecycleQuery(query)) {
        component = <LifecycleInsightQuery query={query} />
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
