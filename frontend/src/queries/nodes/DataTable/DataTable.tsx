import './DataTable.scss'
import {
    AnyResponseType,
    DataTableNode,
    EventsNode,
    EventsQuery,
    HogQLQuery,
    PersonsNode,
    PersonsQuery,
} from '~/queries/schema'
import { QueryContext } from '~/queries/types'

import { useCallback, useState } from 'react'
import { BindLogic, useValues } from 'kea'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { EventName } from '~/queries/nodes/EventsNode/EventName'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { EventDetails } from 'scenes/events/EventDetails'
import { EventRowActions } from '~/queries/nodes/DataTable/EventRowActions'
import { DataTableExport } from '~/queries/nodes/DataTable/DataTableExport'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { LoadNext } from '~/queries/nodes/DataNode/LoadNext'
import { renderColumnMeta } from '~/queries/nodes/DataTable/renderColumnMeta'
import { renderColumn } from '~/queries/nodes/DataTable/renderColumn'
import { AutoLoad } from '~/queries/nodes/DataNode/AutoLoad'
import { dataTableLogic, DataTableLogicProps, DataTableRow } from '~/queries/nodes/DataTable/dataTableLogic'
import { ColumnConfigurator } from '~/queries/nodes/DataTable/ColumnConfigurator/ColumnConfigurator'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import clsx from 'clsx'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { OpenEditorButton } from '~/queries/nodes/Node/OpenEditorButton'
import {
    isEventsQuery,
    isHogQlAggregation,
    isHogQLQuery,
    isPersonsQuery,
    taxonomicEventFilterToHogQL,
    taxonomicPersonFilterToHogQL,
} from '~/queries/utils'
import { PersonPropertyFilters } from '~/queries/nodes/PersonsNode/PersonPropertyFilters'
import { PersonsSearch } from '~/queries/nodes/PersonsNode/PersonsSearch'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import {
    extractExpressionComment,
    getDataNodeDefaultColumns,
    removeExpressionComment,
} from '~/queries/nodes/DataTable/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { EventType } from '~/types'
import { SavedQueries } from '~/queries/nodes/DataTable/SavedQueries'
import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { EditHogQLButton } from '~/queries/nodes/Node/EditHogQLButton'

interface DataTableProps {
    uniqueKey?: string | number
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    /** Custom table columns */
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

const eventGroupTypes = [
    TaxonomicFilterGroupType.HogQLExpression,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]
const personGroupTypes = [TaxonomicFilterGroupType.HogQLExpression, TaxonomicFilterGroupType.PersonProperties]

let uniqueNode = 0

export function DataTable({ uniqueKey, query, setQuery, context, cachedResults }: DataTableProps): JSX.Element {
    const uniqueNodeKey = useState(() => uniqueNode++)
    const [dataKey] = useState(() => `DataNode.${uniqueKey || uniqueNodeKey}`)
    const [vizKey] = useState(() => `DataTable.${uniqueNodeKey}`)

    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: dataKey,
        cachedResults: cachedResults,
    }
    const builtDataNodeLogic = dataNodeLogic(dataNodeLogicProps)

    const {
        response,
        responseLoading,
        responseError,
        queryCancelled,
        canLoadNextData,
        canLoadNewData,
        nextDataLoading,
        newDataLoading,
        highlightedRows,
    } = useValues(builtDataNodeLogic)

    const dataTableLogicProps: DataTableLogicProps = { query, vizKey: vizKey, dataKey: dataKey, context }
    const { dataTableRows, columnsInQuery, columnsInResponse, queryWithDefaults, canSort, sourceFeatures } = useValues(
        dataTableLogic(dataTableLogicProps)
    )

    const {
        showActions,
        showDateRange,
        showSearch,
        showEventFilter,
        showPropertyFilter,
        showHogQLEditor,
        showReload,
        showExport,
        showElapsedTime,
        showColumnConfigurator,
        showPersistentColumnConfigurator,
        showSavedQueries,
        expandable,
        embedded,
        showOpenEditorButton,
        showResultsTable,
        showTimings,
    } = queryWithDefaults

    const isReadOnly = setQuery === undefined

    const eventActionsColumnShown =
        showActions && sourceFeatures.has(QueryFeature.eventActionsColumn) && columnsInResponse?.includes('*')
    const columnsInLemonTable = sourceFeatures.has(QueryFeature.columnsInResponse)
        ? columnsInResponse ?? columnsInQuery
        : columnsInQuery

    const groupTypes = isPersonsQuery(query.source) ? personGroupTypes : eventGroupTypes
    const hogQLTable = isPersonsQuery(query.source) ? 'persons' : 'events'

    const lemonColumns: LemonTableColumn<DataTableRow, any>[] = [
        ...columnsInLemonTable.map((key, index) => ({
            dataIndex: key as any,
            ...renderColumnMeta(key, query, context),
            render: function RenderDataTableColumn(_: any, { result, label }: DataTableRow) {
                if (label) {
                    if (index === (expandable ? 1 : 0)) {
                        return {
                            children: label,
                            props: { colSpan: columnsInLemonTable.length + (eventActionsColumnShown ? 1 : 0) },
                        }
                    } else {
                        return { props: { colSpan: 0 } }
                    }
                } else if (result) {
                    if (sourceFeatures.has(QueryFeature.resultIsArrayOfArrays)) {
                        return renderColumn(key, result[index], result, query, setQuery, context)
                    }
                    return renderColumn(key, result[key], result, query, setQuery, context)
                }
            },
            sorter: undefined, // using custom sorting code
            more:
                !isReadOnly && showActions && sourceFeatures.has(QueryFeature.selectAndOrderByColumns) ? (
                    <>
                        <div className="px-2 py-1">
                            <div className="font-mono font-bold">{extractExpressionComment(key)}</div>
                            {extractExpressionComment(key) !== removeExpressionComment(key) && (
                                <div className="font-mono">{removeExpressionComment(key)}</div>
                            )}
                        </div>
                        <LemonDivider />
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value={key}
                            groupTypes={groupTypes}
                            hogQLTable={hogQLTable}
                            renderValue={() => <>Edit column</>}
                            type="tertiary"
                            fullWidth
                            onChange={(v, g) => {
                                const hogQl = isPersonsQuery(query.source)
                                    ? taxonomicPersonFilterToHogQL(g, v)
                                    : taxonomicEventFilterToHogQL(g, v)
                                if (setQuery && hogQl && sourceFeatures.has(QueryFeature.selectAndOrderByColumns)) {
                                    // Typecasting to a query type with select and order_by fields.
                                    // The actual query may or may not be an events query.
                                    const source = query.source as EventsQuery
                                    const columns = getDataNodeDefaultColumns(source)
                                    const isAggregation = isHogQlAggregation(hogQl)
                                    const isOrderBy = source.orderBy?.[0] === key
                                    const isDescOrderBy = source.orderBy?.[0] === `${key} DESC`
                                    setQuery({
                                        ...query,
                                        source: {
                                            ...source,
                                            select: columns
                                                .map((s, i) => (i === index ? hogQl : s))
                                                .filter((c) =>
                                                    isAggregation ? c !== '*' && c !== 'person.$delete' : true
                                                ),
                                            orderBy:
                                                isOrderBy || isDescOrderBy
                                                    ? [isDescOrderBy ? `${hogQl} DESC` : hogQl]
                                                    : source.orderBy,
                                        },
                                    })
                                }
                            }}
                        />
                        <LemonDivider />
                        {canSort && key !== 'person.$delete' ? (
                            <>
                                <LemonButton
                                    fullWidth
                                    status={(query.source as EventsQuery)?.orderBy?.[0] === key ? 'primary' : 'stealth'}
                                    data-attr="datatable-sort-asc"
                                    onClick={() => {
                                        setQuery?.({
                                            ...query,
                                            source: {
                                                ...query.source,
                                                orderBy: [key],
                                            } as EventsQuery,
                                        })
                                    }}
                                >
                                    Sort ascending
                                </LemonButton>
                                <LemonButton
                                    fullWidth
                                    status={
                                        (query.source as EventsQuery)?.orderBy?.[0] === `${key} DESC`
                                            ? 'primary'
                                            : 'stealth'
                                    }
                                    data-attr="datatable-sort-desc"
                                    onClick={() => {
                                        setQuery?.({
                                            ...query,
                                            source: {
                                                ...query.source,
                                                orderBy: [`${key} DESC`],
                                            } as EventsQuery,
                                        })
                                    }}
                                >
                                    Sort descending
                                </LemonButton>
                                <LemonDivider />
                            </>
                        ) : null}
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value={''}
                            groupTypes={groupTypes}
                            hogQLTable={hogQLTable}
                            placeholder={<span className="not-italic">Add column left</span>}
                            data-attr="datatable-add-column-left"
                            type="tertiary"
                            fullWidth
                            onChange={(v, g) => {
                                const hogQl = isPersonsQuery(query.source)
                                    ? taxonomicPersonFilterToHogQL(g, v)
                                    : taxonomicEventFilterToHogQL(g, v)
                                if (setQuery && hogQl && sourceFeatures.has(QueryFeature.selectAndOrderByColumns)) {
                                    const isAggregation = isHogQlAggregation(hogQl)
                                    const source = query.source as EventsQuery
                                    const columns = getDataNodeDefaultColumns(source)
                                    setQuery({
                                        ...query,
                                        source: {
                                            ...source,
                                            select: [...columns.slice(0, index), hogQl, ...columns.slice(index)].filter(
                                                (c) => (isAggregation ? c !== '*' && c !== 'person.$delete' : true)
                                            ),
                                        } as EventsQuery | PersonsQuery,
                                    })
                                }
                            }}
                        />
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value={''}
                            groupTypes={groupTypes}
                            hogQLTable={hogQLTable}
                            placeholder={<span className="not-italic">Add column right</span>}
                            data-attr="datatable-add-column-right"
                            type="tertiary"
                            fullWidth
                            onChange={(v, g) => {
                                const hogQl = isPersonsQuery(query.source)
                                    ? taxonomicPersonFilterToHogQL(g, v)
                                    : taxonomicEventFilterToHogQL(g, v)
                                if (setQuery && hogQl && sourceFeatures.has(QueryFeature.selectAndOrderByColumns)) {
                                    const isAggregation = isHogQlAggregation(hogQl)
                                    const source = query.source as EventsQuery
                                    const columns = getDataNodeDefaultColumns(source)
                                    setQuery?.({
                                        ...query,
                                        source: {
                                            ...source,
                                            select: [
                                                ...columns.slice(0, index + 1),
                                                hogQl,
                                                ...columns.slice(index + 1),
                                            ].filter((c) =>
                                                isAggregation ? c !== '*' && c !== 'person.$delete' : true
                                            ),
                                        } as EventsQuery | PersonsQuery,
                                    })
                                }
                            }}
                        />
                        {columnsInQuery.filter((c) => c !== '*').length > 1 ? (
                            <>
                                <LemonDivider />
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    data-attr="datatable-remove-column"
                                    onClick={() => {
                                        const cleanColumnKey = removeExpressionComment(key)
                                        const newSource: EventsQuery = {
                                            ...(query.source as EventsQuery),
                                            select: (query.source as EventsQuery).select.filter((_, i) => i !== index),
                                            // remove the current column from orderBy if it's there
                                            orderBy: (query.source as EventsQuery).orderBy?.find(
                                                (orderKey) =>
                                                    removeExpressionComment(orderKey) === cleanColumnKey ||
                                                    removeExpressionComment(orderKey) === `-${cleanColumnKey}`
                                            )
                                                ? undefined
                                                : (query.source as EventsQuery).orderBy,
                                        }
                                        setQuery?.({
                                            ...query,
                                            source: newSource,
                                        })
                                    }}
                                >
                                    Remove column
                                </LemonButton>
                            </>
                        ) : null}
                    </>
                ) : undefined,
        })),
        ...(eventActionsColumnShown
            ? [
                  {
                      dataIndex: '__more' as any,
                      title: '',
                      render: function RenderMore(_: any, { label, result }: DataTableRow) {
                          if (label) {
                              return { props: { colSpan: 0 } }
                          }
                          if (result && columnsInResponse?.includes('*')) {
                              return <EventRowActions event={result[columnsInResponse.indexOf('*')]} />
                          }
                          return null
                      },
                      width: 0,
                  },
              ]
            : []),
    ].filter((column) => !query.hiddenColumns?.includes(column.dataIndex) && column.dataIndex !== '*')

    const setQuerySource = useCallback(
        (source: EventsNode | EventsQuery | PersonsNode | PersonsQuery | HogQLQuery) =>
            setQuery?.({ ...query, source }),
        [setQuery]
    )

    const firstRowLeft = [
        showDateRange && sourceFeatures.has(QueryFeature.dateRangePicker) ? (
            <DateRange key="date-range" query={query.source} setQuery={setQuerySource} />
        ) : null,
        showEventFilter && sourceFeatures.has(QueryFeature.eventNameFilter) ? (
            <EventName key="event-name" query={query.source as EventsQuery} setQuery={setQuerySource} />
        ) : null,
        showSearch && sourceFeatures.has(QueryFeature.personsSearch) ? (
            <PersonsSearch key="persons-search" query={query.source as PersonsNode} setQuery={setQuerySource} />
        ) : null,
        showPropertyFilter && sourceFeatures.has(QueryFeature.eventPropertyFilters) ? (
            <EventPropertyFilters key="event-property" query={query.source as EventsQuery} setQuery={setQuerySource} />
        ) : null,
        showPropertyFilter && sourceFeatures.has(QueryFeature.personPropertyFilters) ? (
            <PersonPropertyFilters
                key="person-property"
                query={query.source as PersonsNode}
                setQuery={setQuerySource}
            />
        ) : null,
    ].filter((x) => !!x)

    const firstRowRight = [
        showSavedQueries && sourceFeatures.has(QueryFeature.savedEventsQueries) ? (
            <SavedQueries key="saved-queries" query={query} setQuery={setQuery} />
        ) : null,
    ].filter((x) => !!x)

    const secondRowLeft = [
        showReload ? <Reload key="reload" /> : null,
        showReload && canLoadNewData ? <AutoLoad key="auto-load" /> : null,
        showElapsedTime ? <ElapsedTime key="elapsed-time" showTimings={showTimings} /> : null,
    ].filter((x) => !!x)

    const secondRowRight = [
        (showColumnConfigurator || showPersistentColumnConfigurator) &&
        sourceFeatures.has(QueryFeature.columnConfigurator) ? (
            <ColumnConfigurator key="column-configurator" query={query} setQuery={setQuery} />
        ) : null,
        showExport ? <DataTableExport key="data-table-export" query={query} setQuery={setQuery} /> : null,
    ].filter((x) => !!x)

    const showFirstRow = !isReadOnly && (firstRowLeft.length > 0 || firstRowRight.length > 0)
    const showSecondRow = !isReadOnly && (secondRowLeft.length > 0 || secondRowRight.length > 0)
    const inlineEditorButtonOnRow = showFirstRow ? 1 : showSecondRow ? 2 : 0

    const editorButton = (
        <>
            <OpenEditorButton query={query} />
            {response?.hogql ? <EditHogQLButton hogql={response.hogql} /> : null}
        </>
    )

    // The editor button moved under "export". Show only if there's no export button.
    if (!showExport && showOpenEditorButton && !isReadOnly) {
        if (inlineEditorButtonOnRow === 1) {
            firstRowRight.push(editorButton)
        } else if (inlineEditorButtonOnRow === 2) {
            secondRowRight.push(editorButton)
        }
    }

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="relative w-full flex flex-col gap-4 flex-1 overflow-hidden">
                    {showHogQLEditor && isHogQLQuery(query.source) && !isReadOnly ? (
                        <HogQLQueryEditor query={query.source} setQuery={setQuerySource} embedded={embedded} />
                    ) : null}
                    {showFirstRow && (
                        <div className="flex gap-4 items-center flex-wrap">
                            {firstRowLeft}
                            {firstRowLeft.length > 0 && firstRowRight.length > 0 ? <div className="flex-1" /> : null}
                            {firstRowRight}
                        </div>
                    )}
                    {showFirstRow && showSecondRow && <LemonDivider className="my-0" />}
                    {showSecondRow && (
                        <div className="flex gap-4 justify-between flex-wrap">
                            <div className="flex gap-4 items-center">{secondRowLeft}</div>
                            <div className="flex gap-4 items-center">{secondRowRight}</div>
                        </div>
                    )}
                    {showOpenEditorButton && inlineEditorButtonOnRow === 0 && !isReadOnly ? (
                        <div className="absolute right-0 z-10 p-1">{editorButton}</div>
                    ) : null}
                    {showResultsTable && (
                        <LemonTable
                            className="DataTable"
                            loading={responseLoading && !nextDataLoading && !newDataLoading}
                            columns={lemonColumns}
                            embedded={embedded}
                            key={
                                [...(columnsInResponse ?? []), ...columnsInQuery].join(
                                    '::'
                                ) /* Bust the LemonTable cache when columns change */
                            }
                            dataSource={dataTableRows ?? []}
                            rowKey={({ result }: DataTableRow, rowIndex) => {
                                if (result) {
                                    if (
                                        sourceFeatures.has(QueryFeature.resultIsArrayOfArrays) &&
                                        sourceFeatures.has(QueryFeature.columnsInResponse)
                                    ) {
                                        if (columnsInResponse?.includes('*')) {
                                            return result[columnsInResponse.indexOf('*')].uuid
                                        } else if (columnsInResponse?.includes('uuid')) {
                                            return result[columnsInResponse.indexOf('uuid')]
                                        } else if (columnsInResponse?.includes('id')) {
                                            return result[columnsInResponse.indexOf('id')]
                                        }
                                    }
                                    return (
                                        (result && 'uuid' in result ? (result as any).uuid : null) ??
                                        (result && 'id' in result ? (result as any).id : null) ??
                                        JSON.stringify(result ?? rowIndex)
                                    )
                                }
                                return rowIndex
                            }}
                            sorting={null}
                            useURLForSorting={false}
                            emptyState={
                                responseError ? (
                                    sourceFeatures.has(QueryFeature.displayResponseError) ? (
                                        <InsightErrorState
                                            excludeDetail
                                            title={
                                                queryCancelled
                                                    ? 'The query was cancelled'
                                                    : response && 'error' in response
                                                    ? (response as any).error
                                                    : responseError
                                            }
                                        />
                                    ) : (
                                        <InsightErrorState />
                                    )
                                ) : (
                                    <InsightEmptyState
                                        heading={context?.emptyStateHeading}
                                        detail={context?.emptyStateDetail}
                                    />
                                )
                            }
                            expandable={
                                expandable && columnsInResponse?.includes('*')
                                    ? {
                                          expandedRowRender: function renderExpand({ result }) {
                                              if (isEventsQuery(query.source) && Array.isArray(result)) {
                                                  return (
                                                      <EventDetails
                                                          event={result[columnsInResponse.indexOf('*')] ?? {}}
                                                          useReactJsonView
                                                      />
                                                  )
                                              }
                                              if (result && !Array.isArray(result)) {
                                                  return <EventDetails event={result as EventType} useReactJsonView />
                                              }
                                          },
                                          rowExpandable: ({ result }) => !!result,
                                          noIndent: true,
                                          expandedRowClassName: ({ result }) => {
                                              const record = Array.isArray(result) ? result[0] : result
                                              return record && record['event'] === '$exception'
                                                  ? 'border border-x-danger-dark bg-danger-highlight'
                                                  : null
                                          },
                                      }
                                    : undefined
                            }
                            rowClassName={({ result, label }) =>
                                clsx('DataTable__row', {
                                    'DataTable__row--highlight_once': result && highlightedRows.has(result),
                                    'DataTable__row--category_row': !!label,
                                    'border border-x-danger-dark bg-danger-highlight':
                                        result && result[0] && result[0]['event'] === '$exception',
                                })
                            }
                            footer={
                                canLoadNextData &&
                                ((response as any).results.length > 0 ||
                                    (response as any).result.length > 0 ||
                                    !responseLoading) && <LoadNext query={query.source} />
                            }
                            onRow={context?.rowProps}
                        />
                    )}
                    {/* TODO: this doesn't seem like the right solution... */}
                    <SessionPlayerModal />
                    <PersonDeleteModal />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
