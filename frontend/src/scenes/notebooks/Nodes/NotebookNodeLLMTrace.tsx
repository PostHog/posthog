import { BindLogic, useActions, useValues } from 'kea'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { groupsModel } from '~/models/groupsModel'
import { Query } from '~/queries/Query/Query'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableExport } from '~/queries/nodes/DataTable/DataTableExport'
import { DataTableSavedFilters } from '~/queries/nodes/DataTable/DataTableSavedFilters'
import { DataTableSavedFiltersButton } from '~/queries/nodes/DataTable/DataTableSavedFiltersButton'
import { dataTableLogic } from '~/queries/nodes/DataTable/dataTableLogic'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { TracesQuery } from '~/queries/schema/schema-general'
import { isTracesQuery } from '~/queries/utils'

import { LLMAnalyticsSetupPrompt } from 'products/llm_analytics/frontend/LLMAnalyticsSetupPrompt'
import { useTracesQueryContext } from 'products/llm_analytics/frontend/LLMAnalyticsTracesScene'
import { llmAnalyticsLogic } from 'products/llm_analytics/frontend/llmAnalyticsLogic'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { createPostHogWidgetNode } from './NodeWrapper'
import { notebookNodeLogic } from './notebookNodeLogic'

const Component = ({ attributes }: NotebookNodeProps<NotebookNodeLLMTraceAttributes>): JSX.Element | null => {
    const { expanded } = useValues(notebookNodeLogic)
    const { personId } = attributes
    const { setDates, setShouldFilterTestAccounts, setPropertyFilters, setTracesQuery } = useActions(
        llmAnalyticsLogic({ personId })
    )
    const { tracesQuery } = useValues(llmAnalyticsLogic({ personId }))
    const context = useTracesQueryContext()

    if (!expanded) {
        return null
    }

    return (
        <BindLogic logic={dataNodeLogic} props={{ key: personId }}>
            <LLMAnalyticsSetupPrompt className="border-none">
                <Query
                    query={{
                        ...tracesQuery,
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
            </LLMAnalyticsSetupPrompt>
        </BindLogic>
    )
}

const Settings = ({ attributes }: NotebookNodeAttributeProperties<NotebookNodeLLMTraceAttributes>): JSX.Element => {
    const { personId, nodeId } = attributes
    const { setDates, setPropertyFilters, setTracesQuery } = useActions(llmAnalyticsLogic({ personId }))
    const { tracesQuery } = useValues(llmAnalyticsLogic({ personId }))
    const { groupsTaxonomicTypes } = useValues(groupsModel)

    return (
        <div className="p-2 space-y-2 mb-2">
            <BindLogic
                logic={dataTableLogic}
                props={{ vizKey: nodeId, dataKey: personId, query: tracesQuery, dataNodeLogicKey: nodeId }}
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
                            fileNameForExport={`${personId}-llm-traces-export`}
                        />
                    </div>
                </BindLogic>
            </BindLogic>
        </div>
    )
}

type NotebookNodeLLMTraceAttributes = {
    personId?: string
}

export const NotebookNodeLLMTrace = createPostHogWidgetNode<NotebookNodeLLMTraceAttributes>({
    nodeType: NotebookNodeType.LLMTrace,
    titlePlaceholder: 'Traces',
    Component,
    Settings,
    resizeable: false,
    expandable: true,
    startExpanded: true,
    attributes: {
        personId: {},
    },
})
