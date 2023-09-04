import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind, QuerySchema } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useMemo } from 'react'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import clsx from 'clsx'
import { IconSettings } from 'lib/lemon-ui/icons'

const DEFAULT_QUERY: QuerySchema = {
    kind: NodeKind.DataTableNode,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'event', 'person', 'timestamp'],
        orderBy: ['timestamp DESC'],
        after: '-24h',
        limit: 100,
    },
}

const Component = (props: NotebookNodeViewProps<NotebookNodeQueryAttributes>): JSX.Element | null => {
    const { query } = props.attributes
    const logic = insightLogic({ dashboardItemId: 'new' })
    const { insightProps } = useValues(logic)
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = false
            modifiedQuery.showHogQLEditor = false
            modifiedQuery.embedded = true
        }

        return modifiedQuery
    }, [query])

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className={clsx('flex flex-1 flex-col overflow-hidden')}>
                <Query query={modifiedQuery} uniqueKey={nodeLogic.props.nodeId} />
            </div>
        </BindLogic>
    )
}

type NotebookNodeQueryAttributes = {
    query: QuerySchema
}

export const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeQueryAttributes>): JSX.Element => {
    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...attributes.query }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.showHogQLEditor = true
            modifiedQuery.showResultsTable = false
            modifiedQuery.showReload = true
        }

        return modifiedQuery
    }, [attributes.query])

    return (
        <div className="p-3">
            <Query
                query={modifiedQuery}
                setQuery={(t) => {
                    if (t.kind === NodeKind.DataTableNode) {
                        updateAttributes({
                            query: { ...attributes.query, source: (t as DataTableNode).source } as QuerySchema,
                        })
                    }
                }}
                uniqueKey={attributes.nodeId}
            />
        </div>
    )
}

export const NotebookNodeQuery = createPostHogWidgetNode<NotebookNodeQueryAttributes>({
    nodeType: NotebookNodeType.Query,
    title: (attributes) => {
        const query = attributes.query
        let title = 'HogQL'
        if (NodeKind.DataTableNode === query.kind) {
            if (query.source.kind) {
                title = query.source.kind.replace('Node', '').replace('Query', '')
            } else {
                title = 'Data exploration'
            }
        }
        return Promise.resolve(title)
    },
    Component,
    heightEstimate: 500,
    minHeight: 200,
    resizeable: true,
    startExpanded: true,
    attributes: {
        query: {
            default: DEFAULT_QUERY,
        },
    },
    widgets: [
        {
            key: 'settings',
            label: 'Settings',
            icon: <IconSettings />,
            Component: Settings,
        },
    ],
})
