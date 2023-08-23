import { Query } from '~/queries/Query/Query'
import { DataTableNode, NodeKind, QuerySchema } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { ChartDisplayType, InsightShortId, NotebookNodeType, PropertyMathType } from '~/types'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useJsonNodeState } from './utils'
import { useEffect, useMemo } from 'react'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps, NotebookNodeWidgetSettings } from '../Notebook/utils'
import clsx from 'clsx'
import { IconSettings } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

const SAMPLE_QUERY: QuerySchema = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        filterTestAccounts: true,
        dateRange: {
            date_from: '-90d',
        },
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                math: PropertyMathType.Average,
            },
        ],
        interval: 'week',
        trendsFilter: {
            display: ChartDisplayType.ActionsAreaGraph,
        },
    },
    full: true,
}

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
    const [query] = useJsonNodeState<QuerySchema>(props.node.attrs, props.updateAttributes, 'query')
    const logic = insightLogic({ dashboardItemId: 'new' })
    const { insightProps } = useValues(logic)
    const { setTitle } = useActions(notebookNodeLogic)
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)

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
        const modifiedQuery = { ...SAMPLE_QUERY }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = false
            modifiedQuery.showHogQLEditor = false
            modifiedQuery.embedded = true
        } else if (NodeKind.InsightVizNode === modifiedQuery.kind) {
            modifiedQuery.showFilters = false
            modifiedQuery.showHeader = false
            modifiedQuery.showTable = false
            modifiedQuery.showCorrelationTable = false
        }

        return modifiedQuery
    }, [query])

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div
                className={clsx(
                    'flex flex-1 flex-col',
                    NodeKind.DataTableNode === modifiedQuery.kind && 'overflow-hidden',
                    NodeKind.InsightVizNode === modifiedQuery.kind && 'overflow-scroll'
                )}
            >
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
}: NotebookNodeWidgetSettings<NotebookNodeQueryAttributes>): JSX.Element => {
    const [query, setQuery] = useJsonNodeState<QuerySchema>(attributes, updateAttributes, 'query')

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...SAMPLE_QUERY }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.showHogQLEditor = true
            modifiedQuery.showResults = false
            modifiedQuery.showReload = true
        } else if (NodeKind.InsightVizNode === modifiedQuery.kind) {
            modifiedQuery.showFilters = true
            modifiedQuery.showResults = false
            modifiedQuery.embedded = true
        }

        return modifiedQuery
    }, [query])

    return (
        <div className="p-3">
            <Query
                query={modifiedQuery}
                setQuery={(t) => {
                    if (t.kind === NodeKind.DataTableNode) {
                        setQuery({ ...query, source: (t as DataTableNode).source } as QuerySchema)
                    }
                }}
                readOnly={false}
                uniqueKey={attributes.nodeId}
            />
        </div>
    )
}

export const NotebookNodeQuery = createPostHogWidgetNode<NotebookNodeQueryAttributes>({
    nodeType: NotebookNodeType.Query,
    title: 'Query', // TODO: allow this to be updated from the component
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
    pasteOptions: {
        find: urls.insightView('(.+)' as InsightShortId),
        getAttributes: async (match) => {
            return {
                query: {
                    kind: NodeKind.SavedInsightNode,
                    shortId: match[1] as InsightShortId,
                },
            }
        },
    },
})
