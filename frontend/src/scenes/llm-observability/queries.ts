import { DataTableNode, NodeKind, TracesQuery } from '~/queries/schema/schema-general'

type GetTracesQueryParams = Pick<TracesQuery, 'limit'>

export function getTracesQuery({ limit }: GetTracesQueryParams): DataTableNode {
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.TracesQuery,
            limit: limit,
        },
        showActions: false,
        showTimings: false,
        // columns: columns,
    }
}
