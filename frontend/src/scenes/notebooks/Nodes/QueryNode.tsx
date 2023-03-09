import { mergeAttributes, Node } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { useState } from 'react'
import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'

const DEFAULT_QUERY: QuerySchema = {
    kind: NodeKind.DataTableNode,
    full: false,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'event', 'person', 'timestamp'],
        orderBy: ['timestamp DESC'],
        after: '-24h',
        limit: 100,
    },
    propertiesViaUrl: false,
    showSavedQueries: false,
}

const Component = (): JSX.Element => {
    const [query, setQuery] = useState<QuerySchema>(DEFAULT_QUERY)

    return (
        <NodeWrapper className={NodeType.Query}>
            <div className="max-h-60 overflow-y-auto">
                <Query query={query} setQuery={(t) => setQuery(t)} />
            </div>
        </NodeWrapper>
    )
}

export const QueryNode = Node.create({
    name: NodeType.Query,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            count: {
                default: 0,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NodeType.Query,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NodeType.Query, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
