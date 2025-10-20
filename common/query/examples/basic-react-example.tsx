import { useMemo } from 'react'

import { type Node, NodeKind, Query } from '@posthog/query'

export function BasicReactExample(): JSX.Element {
    const query = useMemo<Node>(
        () => ({
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.EventsQuery,
                select: ['count()'],
                limit: 10,
            },
        }),
        []
    )

    return <Query query={query} readOnly embedded />
}
