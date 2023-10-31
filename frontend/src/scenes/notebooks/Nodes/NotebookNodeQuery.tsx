import { Query } from '~/queries/Query/Query'
import { DataTableNode, InsightQueryNode, InsightVizNode, NodeKind, QuerySchema } from '~/queries/schema'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { InsightLogicProps, InsightShortId, NotebookNodeType } from '~/types'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useMemo } from 'react'
import { notebookNodeLogic } from './notebookNodeLogic'
import { NotebookNodeProps, NotebookNodeAttributeProperties } from '../Notebook/utils'
import { containsHogQLQuery, isHogQLQuery, isNodeWithSource } from '~/queries/utils'
import { LemonButton } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { urls } from 'scenes/urls'

import './NotebookNodeQuery.scss'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { JSONContent } from '@tiptap/core'

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

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeQueryAttributes>): JSX.Element | null => {
    const { query, nodeId } = attributes
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)
    const { setTitlePlaceholder } = useActions(nodeLogic)

    useEffect(() => {
        let title = 'Query'

        if (query.kind === NodeKind.DataTableNode) {
            if (query.source.kind) {
                title = query.source.kind.replace('Node', '').replace('Query', '')
            } else {
                title = 'Data exploration'
            }
        }
        if (query.kind === NodeKind.InsightVizNode) {
            if (query.source.kind) {
                title = query.source.kind.replace('Node', '').replace('Query', '')
            } else {
                title = 'Insight'
            }
        }
        if (query.kind === NodeKind.SavedInsightNode) {
            const logic = insightLogic.findMounted({ dashboardItemId: query.shortId })
            title = (logic?.values.insight.name || logic?.values.insight.derived_name) ?? 'Saved Insight'
        }

        setTitlePlaceholder(title)
    }, [query])

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query, full: false }

        if (NodeKind.DataTableNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = false
            modifiedQuery.showHogQLEditor = false
            modifiedQuery.embedded = true
        }

        if (NodeKind.InsightVizNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
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
            <Query query={modifiedQuery} uniqueKey={nodeId} readOnly={true} />
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
    const { query } = attributes

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query, full: false }

        if (NodeKind.DataTableNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.showHogQLEditor = true
            modifiedQuery.showResultsTable = false

            modifiedQuery.showReload = true
            modifiedQuery.showElapsedTime = false
            modifiedQuery.showTimings = false

            modifiedQuery.embedded = true
            modifiedQuery.showActions = true

            modifiedQuery.showDateRange = true
            modifiedQuery.showEventFilter = true
            modifiedQuery.showSearch = true
            modifiedQuery.showPropertyFilter = true
            modifiedQuery.showColumnConfigurator = true
        }

        if (NodeKind.InsightVizNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
            modifiedQuery.showFilters = true
            modifiedQuery.showResults = false
            modifiedQuery.embedded = true
        }

        return modifiedQuery
    }, [query])

    const detachSavedInsight = (): void => {
        if (attributes.query.kind === NodeKind.SavedInsightNode) {
            const insightProps: InsightLogicProps = { dashboardItemId: attributes.query.shortId }
            const dataLogic = insightDataLogic.findMounted(insightProps)

            if (dataLogic) {
                updateAttributes({ query: dataLogic.values.query as QuerySchema })
            }
        }
    }

    return attributes.query.kind === NodeKind.SavedInsightNode ? (
        <div className="p-3 space-y-2">
            <div className="text-lg font-semibold">Insight created outside of this notebook</div>
            <div>
                Changes made to the original insight will be reflected in the notebook. Or you can detach from the
                insight to make changes independently in the notebook.
            </div>

            <div className="space-y-2">
                <LemonButton
                    center={true}
                    type="secondary"
                    fullWidth
                    className="flex flex-1"
                    to={urls.insightEdit(attributes.query.shortId)}
                >
                    Edit the insight
                </LemonButton>
                <LemonButton
                    center={true}
                    fullWidth
                    type="secondary"
                    className="flex flex-1"
                    onClick={detachSavedInsight}
                >
                    Detach from insight
                </LemonButton>
            </div>
        </div>
    ) : (
        <div className="p-3">
            <Query
                query={modifiedQuery}
                uniqueKey={attributes.nodeId}
                readOnly={false}
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
    titlePlaceholder: 'Query',
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
    href: (attrs) =>
        attrs.query.kind === NodeKind.SavedInsightNode ? urls.insightView(attrs.query.shortId) : undefined,
    Settings,
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

export function buildInsightVizQueryContent(source: InsightQueryNode): JSONContent {
    return buildNodeQueryContent({ kind: NodeKind.InsightVizNode, source: source })
}

export function buildNodeQueryContent(query: QuerySchema): JSONContent {
    return {
        type: NotebookNodeType.Query,
        attrs: {
            query: query,
            __init: {
                showSettings: true,
            },
        },
    }
}
