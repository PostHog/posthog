import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { defineNotebookWidgetViews, getNotebookWidgetDefaultView } from 'scenes/notebooks/notebookWidgetCatalog'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { DataTableExport } from '~/queries/nodes/DataTable/DataTableExport'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { DataTableSavedFilters } from '~/queries/nodes/DataTable/DataTableSavedFilters'
import { DataTableSavedFiltersButton } from '~/queries/nodes/DataTable/DataTableSavedFiltersButton'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { Query } from '~/queries/Query/Query'
import { TracesQuery } from '~/queries/schema/schema-general'
import { isTracesQuery } from '~/queries/utils'

import { aiObservabilitySharedLogic } from 'products/ai_observability/frontend/aiObservabilitySharedLogic'
import {
    aiObservabilityTraceDataLogic,
    type aiObservabilityTraceDataLogicValues,
} from 'products/ai_observability/frontend/aiObservabilityTraceDataLogic'
import { useTracesQueryContext } from 'products/ai_observability/frontend/AIObservabilityTracesScene'
import { AIObservabilityTraceEvents } from 'products/ai_observability/frontend/components/AIObservabilityTraceEvents'
import { aiObservabilityTracesTabLogic } from 'products/ai_observability/frontend/tabs/aiObservabilityTracesTabLogic'
import { formatLLMCost, formatLLMLatency, formatLLMUsage } from 'products/ai_observability/frontend/utils'
import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from 'products/customer_analytics/frontend/constants'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { getCustomerProfileRemoveMenuItem } from './customerProfileNotebookNodeMenu'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'
import { getLogicKey } from './utils'

const Component = (props: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element | null => {
    return props.attributes.id ? <SingleTraceDetail {...props} /> : <ContextualTraceList {...props} />
}

const ContextualTraceList = ({ attributes }: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element | null => {
    const { expanded, notebookLogic } = useValues(notebookNodeLogic)
    const { setMenuItems } = useActions(notebookNodeLogic)
    const { groupKey, groupTypeIndex, nodeId, personId, tabId } = attributes
    const group = groupKey && groupTypeIndex !== undefined ? { groupKey, groupTypeIndex } : undefined
    const logicKey = getLogicKey({ groupKey, personId, tabId })

    const sharedLogic = aiObservabilitySharedLogic({ logicKey: nodeId, personId, group })
    const tracesLogic = aiObservabilityTracesTabLogic({ logicKey: nodeId, personId, group })
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters } = useActions(sharedLogic)
    const { setTracesQuery } = useActions(tracesLogic)
    const { tracesQuery } = useValues(tracesLogic)
    const context = useTracesQueryContext()
    useAttachedLogic(sharedLogic, notebookLogic)
    useAttachedLogic(tracesLogic, notebookLogic)

    useOnMountEffect(() => {
        const removeMenuItem = getCustomerProfileRemoveMenuItem(NotebookNodeType.LLMTrace)
        if (removeMenuItem) {
            setMenuItems([removeMenuItem])
        }
    })

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={dataNodeLogic} props={{ key: logicKey }}>
            <Query
                uniqueKey={logicKey}
                attachTo={notebookLogic}
                query={{
                    ...tracesQuery,
                    source: {
                        ...tracesQuery.source,
                        tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    embedded: true,
                    showTestAccountFilters: false,
                    showReload: false,
                    showExport: false,
                    showDateRange: false,
                    showPropertyFilter: false,
                    showTimings: false,
                }}
                context={context}
                setQuery={(query) => {
                    if (!isTracesQuery(query.source)) {
                        throw new Error('Invalid query')
                    }
                    setDates(query.source.dateRange?.date_from || null, query.source.dateRange?.date_to || null)
                    setShouldFilterTestAccounts(query.source.filterTestAccounts || false)
                    setPropertyFilters(query.source.properties || [])
                    setTracesQuery(query)
                }}
            />
        </BindLogic>
    )
}

const ContextualSettings = ({
    attributes,
}: NotebookNodeAttributeProperties<NotebookNodeLLMTraceAttributes>): JSX.Element => {
    const { personId, groupKey, groupTypeIndex, nodeId } = attributes
    const group = groupKey && groupTypeIndex !== undefined ? { groupKey, groupTypeIndex } : undefined
    const sharedLogic = aiObservabilitySharedLogic({ logicKey: nodeId, personId, group })
    const tracesLogic = aiObservabilityTracesTabLogic({ logicKey: nodeId, personId, group })
    const { setDates, setPropertyFilters } = useActions(sharedLogic)
    const { setTracesQuery } = useActions(tracesLogic)
    const { tracesQuery } = useValues(tracesLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="p-2 space-y-2 mb-2">
            <BindLogic
                logic={dataTableLogic}
                props={{ vizKey: nodeId, dataKey: nodeId, query: tracesQuery, dataNodeLogicKey: nodeId }}
            >
                <BindLogic logic={dataNodeLogic} props={{ key: nodeId, query: tracesQuery.source }}>
                    <div className="flex gap-2 justify-between">
                        <DateRange
                            key="date-range"
                            query={tracesQuery.source as TracesQuery}
                            setQuery={(query) => {
                                if (!isTracesQuery(query)) {
                                    throw new Error('Invalid query')
                                }
                                setDates(query.dateRange?.date_from || null, query.dateRange?.date_to || null)
                            }}
                        />
                        <EventPropertyFilters
                            key="event-property"
                            query={tracesQuery.source as TracesQuery}
                            setQuery={(query) => {
                                if (!isTracesQuery(query)) {
                                    throw new Error('Invalid query')
                                }
                                setPropertyFilters(query.properties || [])
                            }}
                            taxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.PersonProperties,
                                ...groupsTaxonomicTypes,
                                TaxonomicFilterGroupType.Cohorts,
                                TaxonomicFilterGroupType.HogQLExpression,
                            ]}
                        />
                        <DataTableSavedFiltersButton
                            key="saved-filters-button"
                            uniqueKey={nodeId}
                            query={tracesQuery}
                            setQuery={setTracesQuery}
                        />
                    </div>
                    <DataTableSavedFilters uniqueKey={nodeId} query={tracesQuery} setQuery={setTracesQuery} />
                    <div className="flex justify-between">
                        <Reload key="reload" />
                        <DataTableExport
                            key="data-table-export"
                            query={tracesQuery}
                            setQuery={setTracesQuery}
                            fileNameForExport={`${personId ?? groupKey}-llm-traces-export`}
                        />
                    </div>
                </BindLogic>
            </BindLogic>
        </div>
    )
}

const Settings = (props: NotebookNodeAttributeProperties<NotebookNodeLLMTraceAttributes>): JSX.Element => {
    return props.attributes.id ? <></> : <ContextualSettings {...props} />
}

type NotebookNodeLLMTraceAttributes = {
    id?: string
    view?: string
    personId?: string
    groupKey?: string
    groupTypeIndex?: number
    tabId: string
}

function useSingleTrace(attributes: NotebookNodeLLMTraceAttributes): aiObservabilityTraceDataLogicValues {
    return useValues(aiObservabilityTraceDataLogic({ traceId: attributes.id || '', searchQuery: '' }))
}

function SingleTraceMetadata({ attributes }: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): null {
    const { trace } = useSingleTrace(attributes)
    const { setTitlePlaceholder, setTitleStatus } = useActions(notebookNodeLogic)

    useEffect(() => {
        setTitlePlaceholder(trace?.traceName || trace?.id || 'LLM trace')
        setTitleStatus(trace?.errorCount ? { label: `${trace.errorCount} errors`, type: 'danger' } : null)
    }, [setTitlePlaceholder, setTitleStatus, trace])

    return null
}

function SingleTraceSummary(props: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element {
    const { responseLoading, trace } = useSingleTrace(props.attributes)

    if (responseLoading && !trace) {
        return (
            <div className="p-3">
                <LemonSkeleton className="h-6 w-full" />
            </div>
        )
    }

    return (
        <>
            <SingleTraceMetadata {...props} />
            <div className="flex flex-wrap gap-x-4 gap-y-1 p-3 text-sm">
                <span>{trace ? formatLLMUsage(trace) || 'No token usage' : 'Trace not found'}</span>
                {trace?.totalLatency != null ? <span>{formatLLMLatency(trace.totalLatency)}</span> : null}
                {trace?.totalCost != null ? <span>{formatLLMCost(trace.totalCost)}</span> : null}
            </div>
        </>
    )
}

function SingleTraceDetail(props: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element {
    const { responseLoading, trace } = useSingleTrace(props.attributes)
    const expandedEventIds = new Set(trace?.events.map((event) => event.id))

    return (
        <>
            <SingleTraceMetadata {...props} />
            <div className="flex flex-col gap-2 p-3">
                <AIObservabilityTraceEvents
                    trace={trace}
                    isLoading={responseLoading}
                    expandedEventIds={expandedEventIds}
                    onToggleEventExpand={() => {}}
                />
            </div>
        </>
    )
}

function SingleTraceActivity(props: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element {
    const { responseLoading, trace } = useSingleTrace(props.attributes)

    return (
        <>
            <SingleTraceMetadata {...props} />
            <div className="flex flex-col gap-2 p-3">
                <AIObservabilityTraceEvents
                    trace={trace}
                    isLoading={responseLoading}
                    expandedEventIds={new Set()}
                    onToggleEventExpand={() => {}}
                />
            </div>
        </>
    )
}

function LLMTraceSummary(props: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element | null {
    return props.attributes.id ? <SingleTraceSummary {...props} /> : <ContextualTraceList {...props} />
}

function LLMTraceActivity(props: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element | null {
    return props.attributes.id ? <SingleTraceActivity {...props} /> : <ContextualTraceList {...props} />
}

const LLM_TRACE_NOTEBOOK_WIDGET_VIEWS = defineNotebookWidgetViews<NotebookNodeLLMTraceAttributes, 'LLMTrace'>(
    'LLMTrace',
    {
        summary: LLMTraceSummary,
        activity: LLMTraceActivity,
    }
)

export const NotebookNodeLLMTrace = createPostHogWidgetNode<NotebookNodeLLMTraceAttributes>({
    nodeType: NotebookNodeType.LLMTrace,
    titlePlaceholder: 'Traces',
    editableTitle: false,
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        id: {},
        view: {},
        personId: {},
        groupKey: {},
        groupTypeIndex: {},
        tabId: {},
    },
    href: (attributes) => (attributes.id ? urls.aiObservabilityTrace(attributes.id) : undefined),
    defaultView: getNotebookWidgetDefaultView('LLMTrace'),
    views: LLM_TRACE_NOTEBOOK_WIDGET_VIEWS,
    serializedText: (attributes) => (attributes.id ? 'LLM trace' : 'LLM traces'),
})
