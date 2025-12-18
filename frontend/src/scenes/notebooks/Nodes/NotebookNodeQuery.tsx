import { JSONContent } from '@tiptap/core'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { useSummarizeInsight } from 'scenes/insights/summarizeInsight'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { notebookLogic } from 'scenes/notebooks/Notebook/notebookLogic'
import { urls } from 'scenes/urls'

import { Query } from '~/queries/Query/Query'
import { DataTableNode, InsightQueryNode, InsightVizNode, NodeKind, QuerySchema } from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import {
    containsHogQLQuery,
    isActorsQuery,
    isDataTableNode,
    isEventsQuery,
    isHogQLQuery,
    isInsightVizNode,
    isNodeWithSource,
    isSavedInsightNode,
} from '~/queries/utils'
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

const PYTHON_IDENTIFIER_REGEX = /^[A-Za-z_][A-Za-z0-9_]*$/

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeQueryAttributes>): JSX.Element | null => {
    const { query, nodeId } = attributes
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded } = useValues(nodeLogic)
    const { setTitlePlaceholder } = useActions(nodeLogic)
    const { shortId } = useValues(notebookLogic)
    const summarizeInsight = useSummarizeInsight()

    const outputVariable = attributes.outputVariable ?? ''
    const cleanedVariableName = outputVariable.trim()
    const isVariableNameValid = !cleanedVariableName || PYTHON_IDENTIFIER_REGEX.test(cleanedVariableName)
    const notebookQueryContext = useMemo<QueryContext | undefined>(
        () =>
            shortId
                ? {
                      notebook: {
                          shortId,
                          storeAs: isVariableNameValid && cleanedVariableName ? cleanedVariableName : undefined,
                      },
                  }
                : undefined,
        [cleanedVariableName, isVariableNameValid, shortId]
    )

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
        let modifiedQuery = { ...query, full: false }

        if (isDataTableNode(modifiedQuery) || isSavedInsightNode(modifiedQuery)) {
            modifiedQuery.showOpenEditorButton = false
            modifiedQuery.full = false
            modifiedQuery.showHogQLEditor = false
            modifiedQuery.embedded = true
            modifiedQuery.showTimings = false
        }

        if (isInsightVizNode(modifiedQuery) || isSavedInsightNode(modifiedQuery)) {
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
                <ScrollableShadows direction="vertical" className="flex-1">
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
                        context={notebookQueryContext}
                        embedded
                        readOnly
                    />
                </ScrollableShadows>
                <div className="mt-2">
                    <QueryResultVariableField
                        value={outputVariable}
                        isValid={isVariableNameValid}
                        onChange={(value) => updateAttributes({ outputVariable: value })}
                    />
                </div>
            </BindLogic>
        </div>
    )
}

type NotebookNodeQueryAttributes = {
    query: QuerySchema
    /* Whether canvasFiltersOverride is applied, as we should apply it only once  */
    isDefaultFilterApplied: boolean
    outputVariable?: string
}

export const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeQueryAttributes>): JSX.Element => {
    const { query, isDefaultFilterApplied } = attributes
    const { canvasFiltersOverride, shortId } = useValues(notebookLogic)

    const outputVariable = attributes.outputVariable ?? ''
    const cleanedVariableName = outputVariable.trim()
    const isVariableNameValid = !cleanedVariableName || PYTHON_IDENTIFIER_REGEX.test(cleanedVariableName)
    const notebookQueryContext = useMemo<QueryContext | undefined>(
        () =>
            shortId
                ? {
                      notebook: {
                          shortId,
                          storeAs: isVariableNameValid && cleanedVariableName ? cleanedVariableName : undefined,
                      },
                  }
                : undefined,
        [cleanedVariableName, isVariableNameValid, shortId]
    )

    const modifiedQuery = useMemo(() => {
        const modifiedQuery = { ...query, full: false }

        if (isDataTableNode(modifiedQuery) || isSavedInsightNode(modifiedQuery)) {
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

        if (isInsightVizNode(modifiedQuery) || isSavedInsightNode(modifiedQuery)) {
            modifiedQuery.showFilters = true
            modifiedQuery.showHeader = true
            modifiedQuery.showResults = false
            modifiedQuery.embedded = true
        }

        if (
            isInsightVizNode(modifiedQuery) &&
            !isHogQLQuery(modifiedQuery.source) &&
            !isActorsQuery(modifiedQuery.source) &&
            !isDefaultFilterApplied
        ) {
            modifiedQuery.source.properties = canvasFiltersOverride
            updateAttributes({ ...attributes, isDefaultFilterApplied: true })
        }

        if (isDataTableNode(modifiedQuery) && isEventsQuery(modifiedQuery.source) && !isDefaultFilterApplied) {
            modifiedQuery.source.fixedProperties = canvasFiltersOverride
            updateAttributes({ ...attributes, isDefaultFilterApplied: true })
        }

        return modifiedQuery
    }, [query, canvasFiltersOverride, isDefaultFilterApplied, attributes, updateAttributes])

    const detachSavedInsight = (): void => {
        if (isSavedInsightNode(attributes.query)) {
            const insightProps: InsightLogicProps = { dashboardItemId: attributes.query.shortId }
            const dataLogic = insightDataLogic.findMounted(insightProps)

            if (dataLogic) {
                updateAttributes({ query: dataLogic.values.query as QuerySchema })
            }
        }
    }

    return isSavedInsightNode(attributes.query) ? (
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

            <QueryResultVariableField
                value={outputVariable}
                isValid={isVariableNameValid}
                onChange={(value) => updateAttributes({ outputVariable: value })}
            />
        </div>
    ) : (
        <div className="p-3 space-y-3">
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
                context={notebookQueryContext}
            />

            <QueryResultVariableField
                value={outputVariable}
                isValid={isVariableNameValid}
                onChange={(value) => updateAttributes({ outputVariable: value })}
            />
        </div>
    )
}

const QueryResultVariableField = ({
    value,
    onChange,
    isValid,
}: {
    value: string
    onChange: (value: string) => void
    isValid: boolean
}): JSX.Element => (
    <div className="space-y-1">
        <LemonInput
            label="Store results as"
            value={value}
            placeholder="query1"
            status={isValid ? 'default' : 'danger'}
            onChange={onChange}
        />
        <div className="text-xs text-muted-alt">
            {isValid
                ? 'Optional: save this query response for use in later Python blocks.'
                : 'Use letters, numbers, and underscores, starting with a letter or underscore.'}
        </div>
    </div>
)

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
        isDefaultFilterApplied: {
            default: false,
        },
        outputVariable: {
            default: '',
        },
    },
    href: ({ query }) =>
        isSavedInsightNode(query)
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
                isDefaultFilterApplied: false,
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
