import { isDataNode, isDataTableNode, isLegacyQuery, isInsightQueryNode } from '../utils'
import { DataTable } from '~/queries/nodes/DataTable/DataTable'
import { DataNode } from '~/queries/nodes/DataNode/DataNode'
import { Node } from '~/queries/schema'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { LegacyInsightQuery } from '~/queries/nodes/LegacyInsightQuery/LegacyInsightQuery'
import { InsightQuery } from '~/queries/nodes/InsightQuery/InsightQuery'

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
    } else if (isInsightQueryNode(query)) {
        component = <InsightQuery query={query} />
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
