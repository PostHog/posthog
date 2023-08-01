import { NodeViewProps } from '@tiptap/core'
import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
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

    useEffect(() => {
        // TODO: Set title on parent props
    }, [title])

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
        <BindLogic logic={insightLogic} props={insightProps}>
            <Query query={modifiedQuery} setQuery={(t) => setQuery(t as any)} />
        </BindLogic>
    )
}

export const NotebookNodeQuery = createPostHogWidgetNode({
    nodeType: NotebookNodeType.Query,
    title: 'Query', // TODO: allow this to be updated from the component
    Component,
    heightEstimate: 500,
    resizeable: true,
    attributes: {
        query: {
            default: DEFAULT_QUERY,
        },
    },
})
