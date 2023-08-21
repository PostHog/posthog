import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useJsonNodeState } from './utils'
import { useEffect, useMemo } from 'react'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'
import { notebookLogic } from '../Notebook/notebookLogic'
import clsx from 'clsx'
import DataTable from '~/queries/nodes/DataTable/DataTable'
import { isDataTableNode } from '~/queries/utils'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { IconRefresh } from 'lib/lemon-ui/icons'

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

const Component = (props: NotebookNodeViewProps<NotebookNodeQueryAttributes>): JSX.Element | null => {
    const [query, setQuery] = useJsonNodeState<QuerySchema>(props, 'query')
    const logic = insightLogic({ dashboardItemId: 'new' })
    const { insightProps } = useValues(logic)
    const { setTitle } = useActions(notebookNodeLogic)
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)
    const { isEditable } = useValues(notebookLogic)

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
        setTitle(title)
        // TODO: Set title on parent props
    }, [title])

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = isEditable
        }

        return modifiedQuery
    }, [query, isEditable])

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className={clsx('flex flex-1 flex-col overflow-hidden', isEditable && 'p-3')}>
                <Query
                    query={modifiedQuery}
                    setQuery={(t) => setQuery(t as QuerySchema)}
                    uniqueKey={nodeLogic.props.nodeId}
                >
                    {isDataTableNode(modifiedQuery) && (
                        <>
                            {isEditable && <DataTable.HogQLQueryEditor />}
                            <DataTable.Results isReadOnly={isEditable} embedded={!isEditable} />
                        </>
                    )}
                </Query>
            </div>
        </BindLogic>
    )
}

type NotebookNodeQueryAttributes = {
    query: QuerySchema
}

export const NotebookNodeQuery = createPostHogWidgetNode<NotebookNodeQueryAttributes>({
    nodeType: NotebookNodeType.Query,
    title: 'Query', // TODO: allow this to be updated from the component
    Component,
    heightEstimate: 500,
    minHeight: 600,
    resizeable: true,
    startExpanded: true,
    attributes: {
        query: {
            default: DEFAULT_QUERY,
        },
    },
    widgets: [
        {
            icon: <IconRefresh />,
            onClick: ({ query, nodeId }) => {
                const dataNodeLogicProps = { query: query.source, key: `DataTable.${nodeId}` }
                const builtDataNodeLogic = dataNodeLogic(dataNodeLogicProps)

                builtDataNodeLogic.actions.loadData()
            },
        },
    ],
})
