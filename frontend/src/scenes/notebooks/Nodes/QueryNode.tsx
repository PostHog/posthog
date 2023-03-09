import { mergeAttributes, Node } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { useState } from 'react'
import { defaultDataTableColumns } from '~/queries/nodes/DataTable/utils'
import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'

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
        <NodeViewWrapper className="ph-query">
            <div className="max-h-60 overflow-y-auto">
                <Query query={query} setQuery={(t) => setQuery(t)} />
            </div>
        </NodeViewWrapper>
    )
}

export const QueryNode = Node.create({
    name: 'posthogQuery',
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
                tag: 'ph-query',
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return ['ph-query', mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
