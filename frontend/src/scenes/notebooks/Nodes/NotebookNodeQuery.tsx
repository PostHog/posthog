import { Query } from '~/queries/Query/Query'
import { NodeKind, QuerySchema } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { BaseMathType, ChartDisplayType, InsightShortId, NotebookNodeType } from '~/types'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useJsonNodeState } from './utils'
import { useEffect, useMemo } from 'react'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps } from '../Notebook/utils'
import clsx from 'clsx'
import { urls } from 'scenes/urls'

const SAMPLE_QUERY: QuerySchema = {
    kind: NodeKind.InsightVizNode,
    source: {
        kind: NodeKind.TrendsQuery,
        filterTestAccounts: false,
        dateRange: {
            date_from: '-7d',
        },
        series: [
            {
                kind: NodeKind.EventsNode,
                event: '$pageview',
                name: '$pageview',
                math: BaseMathType.TotalCount,
            },
        ],
        interval: 'day',
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

        modifiedQuery.showHeader = false
        modifiedQuery.showTable = false
        modifiedQuery.showCorrelationTable = false

        return modifiedQuery
    }, [query])

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className={clsx('flex flex-1 flex-col overflow-scroll')}>
                <Query
                    query={modifiedQuery}
                    setQuery={(_) => {
                        debugger
                    }}
                />
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
    minHeight: 200,
    resizeable: false,
    startExpanded: true,
    attributes: {
        query: {
            default: DEFAULT_QUERY,
        },
    },
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
