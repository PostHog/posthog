import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { useEffect, useState } from 'react'
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
    expandable: false,
}

const Component = (props: NodeViewProps): JSX.Element => {
    let propQuery = props.node.attrs.query
    propQuery = typeof propQuery === 'string' ? JSON.parse(propQuery) : propQuery
    const [query, setQuery] = useState<QuerySchema>(propQuery)

    useEffect(() => {
        props.updateAttributes({
            query: JSON.stringify(query),
        })
    }, [query])

    return (
        <NodeWrapper className={NodeType.Query} title="Query">
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
            query: {
                default: DEFAULT_QUERY,
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
