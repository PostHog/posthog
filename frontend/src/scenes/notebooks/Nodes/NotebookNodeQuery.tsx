import { JSONContent } from '@tiptap/core'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, InsightQueryNode, InsightVizNode, NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isHogQLQuery, isInsightVizNode, isNodeWithSource } from '~/queries/utils'
import { InsightLogicProps, InsightShortId } from '~/types'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { notebookNodeLogic } from './notebookNodeLogic'
import { SHORT_CODE_REGEX_MATCH_GROUPS } from './utils'

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

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeQueryAttributes>): JSX.Element | null => {
    const { query, nodeId } = attributes
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)
    const { setTitlePlaceholder } = useActions(nodeLogic)
    const summarizeInsight = useSummarizeInsight()

    const insightLogicProps = {
        dashboardItemId: query.kind === NodeKind.SavedInsightNode ? query.shortId : ('new' as const),
    }
    const { insightName } = useValues(insightLogic(insightLogicProps))

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
            title = summarizeInsight(query)

            if (!title) {
                if (query.source.kind) {
                    title = query.source.kind.replace('Node', '').replace('Query', '')
                } else {
                    title = 'Insight'
                }
            }
        }

        if (query.kind === NodeKind.SavedInsightNode) {
            title = insightName ?? 'Saved Insight'
        }

        setTitlePlaceholder(title)
        // oxlint-disable-next-line exhaustive-deps
    }, [query, insightName])

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query, full: false }

        if (NodeKind.DataTableNode === modifiedQuery.kind || NodeKind.SavedInsightNode === modifiedQuery.kind) {
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = false
            modifiedQuery.showHogQLEditor = false
            modifiedQuery.embedded = true
            modifiedQuery.showTimings = false
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
        <div className="flex flex-1 flex-col h-full" data-attr="notebook-node-query">
            <BindLogic logic={insightLogic} props={insightLogicProps}>
                <Query
                    // use separate keys for the settings and visualization to avoid conflicts with insightProps
                    uniqueKey={nodeId + '-component'}
                    query={modifiedQuery}
                    setQuery={(t) => {
                        updateAttributes({
                            query: {
                                ...attributes.query,
                                source: (t as DataTableNode | InsightVizNode).source,
                            } as QuerySchema,
                        })
                    }}
                    embedded
                    readOnly
                />
            </BindLogic>
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
            modifiedQuery.showExport = true
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
            modifiedQuery.showHeader = true
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
        <div className="p-3 deprecated-space-y-2">
            <div className="text-lg font-semibold">Insight created outside of this notebook</div>
            <div>
                Changes made to the original insight will be reflected in the notebook. Or you can detach from the
                insight to make changes independently in the notebook.
            </div>

            <div className="deprecated-space-y-2">
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
                // use separate keys for the settings and visualization to avoid conflicts with insightProps
                uniqueKey={attributes.nodeId + '-settings'}
                query={modifiedQuery}
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
    resizeable: true,
    startExpanded: true,
    attributes: {
        query: {
            default: DEFAULT_QUERY,
        },
    },
    href: ({ query }) =>
        query.kind === NodeKind.SavedInsightNode
            ? urls.insightView(query.shortId)
            : isInsightVizNode(query)
              ? urls.insightNew({ query })
              : undefined,
    Settings,
    pasteOptions: {
        find: urls.insightView(SHORT_CODE_REGEX_MATCH_GROUPS as InsightShortId),
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
