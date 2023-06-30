import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { BindLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useJsonNodeState } from './utils'
import { useEffect, useMemo, useState } from 'react'

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

const DEFAULT_HEIGHT = 500

const Component = (props: NodeViewProps): JSX.Element => {
    const [query, setQuery] = useJsonNodeState<QuerySchema>(props, 'query')
    const logic = insightLogic({ dashboardItemId: 'new' })
    const { insightProps } = useValues(logic)

    const [editing, setEditing] = useState(false)

    useEffect(() => {
        // We probably want a dedicated edit button for this
        setEditing(props.selected)
    }, [props.selected])

    const title = useMemo(() => {
        if (NodeKind.DataTableNode === query.kind) {
            if (query.source.kind) {
                return query.source.kind.replace('Node', '')
            }
            return 'Data Exploration'
        }
        return 'Query'
    }, [query])

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = editing
        }
        return modifiedQuery
    }, [query, editing])

    return (
        <NodeWrapper nodeType={NotebookNodeType.Query} title={title} heightEstimate={DEFAULT_HEIGHT} {...props}>
            <BindLogic logic={insightLogic} props={insightProps}>
                <Query query={modifiedQuery} setQuery={(t) => setQuery(t as any)} />
            </BindLogic>
        </NodeWrapper>
    )
}

export const NotebookNodeQuery = Node.create({
    name: NotebookNodeType.Query,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            height: {
                default: DEFAULT_HEIGHT,
            },
            query: {
                default: DEFAULT_QUERY,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.Query,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Query, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
