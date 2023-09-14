import { Query } from '~/queries/Query/Query'
import { DataTableNode, InsightVizNode, NodeKind, QuerySchema, SavedInsightNode } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { useMountedLogic, useValues } from 'kea'
import { InsightLogicProps, InsightShortId, NotebookNodeType } from '~/types'
import { useMemo } from 'react'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeViewProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import clsx from 'clsx'
import { IconSettings } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'
import api from 'lib/api'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { containsHogQLQuery, isHogQLQuery, isNodeWithSource } from '~/queries/utils'

import './NotebookNodeQuery.scss'

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
    const { query: propsQuery } = props.attributes
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)

    const insightProps: InsightLogicProps = {
        dashboardItemId: (propsQuery as SavedInsightNode).shortId || 'new',
    }
    const { query } = useValues(insightDataLogic(insightProps))

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...(query as QuerySchema) }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = false
            modifiedQuery.showHogQLEditor = false
            modifiedQuery.embedded = true
        } else if (NodeKind.InsightVizNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
            modifiedQuery.showFilters = false
            modifiedQuery.showHeader = false
            modifiedQuery.showTable = false
            modifiedQuery.showCorrelationTable = false
            modifiedQuery.embedded = true
        }

        return modifiedQuery
    }, [query])

    if (!expanded) {
        return null
    }

    return (
        <div
            className={clsx('flex flex-1 flex-col', NodeKind.DataTableNode === modifiedQuery.kind && 'overflow-hidden')}
        >
            <Query
                query={modifiedQuery}
                uniqueKey={props.attributes.nodeId}
                readOnly={true}
                context={{
                    insightProps,
                }}
            />
        </div>
    )
}

type NotebookNodeQueryAttributes = {
    query: QuerySchema
}

export const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeQueryAttributes>): JSX.Element => {
    const insightProps: InsightLogicProps = {
        dashboardItemId: (attributes.query as SavedInsightNode).shortId || 'new',
    }
    const { query } = useValues(insightDataLogic(insightProps))

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...(query as QuerySchema) }

        if (NodeKind.DataTableNode === modifiedQuery.kind) {
            // We don't want to show the insights button for now
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.showHogQLEditor = true
            modifiedQuery.showResultsTable = false
            modifiedQuery.showReload = false
            modifiedQuery.showElapsedTime = false
        } else if (NodeKind.InsightVizNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
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
                uniqueKey={attributes.nodeId}
                readOnly={false}
                context={{
                    insightProps,
                }}
                setQuery={(t) => {
                    updateAttributes({
                        query: {
                            ...attributes.query,
                            source: (t as DataTableNode | InsightVizNode).source,
                        } as QuerySchema,
                    })
                }}
            />
        </div>
    )
}

export const NotebookNodeQuery = createPostHogWidgetNode<NotebookNodeQueryAttributes>({
    nodeType: NotebookNodeType.Query,
    title: async (attributes) => {
        const query = attributes.query
        let title = 'HogQL'
        if (NodeKind.SavedInsightNode === query.kind) {
            const response = await api.insights.loadInsight(query.shortId)
            title = response.results[0].name?.length
                ? response.results[0].name
                : response.results[0].derived_name || 'Saved insight'
        } else if (NodeKind.DataTableNode === query.kind) {
            if (query.source.kind) {
                title = query.source.kind.replace('Node', '').replace('Query', '')
            } else {
                title = 'Data exploration'
            }
        } else if (NodeKind.InsightVizNode === query.kind) {
            if (query.source.kind) {
                title = query.source.kind.replace('Node', '').replace('Query', '')
            } else {
                title = 'Insight'
            }
        }
        return Promise.resolve(title)
    },
    Component,
    heightEstimate: 500,
    minHeight: 200,
    resizeable: (attrs) => attrs.query.kind === NodeKind.DataTableNode,
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
    serializedText: (attrs) => {
        let text = ''
        const q = attrs.query
        if (containsHogQLQuery(q)) {
            if (isHogQLQuery(q)) {
                text = q.query
            }
            if (isNodeWithSource(q)) {
                text = isHogQLQuery(q.source) ? q.source.query : ''
            }
        }
        return text
    },
})
