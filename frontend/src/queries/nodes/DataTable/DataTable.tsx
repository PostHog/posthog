import './DataTable.scss'
import { DataTableNode, EventsNode, EventsQuery, HogQLQuery, Node, PersonsNode, QueryContext } from '~/queries/schema'
import { useCallback, useState } from 'react'
import { BindLogic, useValues } from 'kea'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonTable, LemonTableColumn } from 'lib/lemon-ui/LemonTable'
import { EventName } from '~/queries/nodes/EventsNode/EventName'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { EventDetails } from 'scenes/events'
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
import { EventBufferNotice } from 'scenes/events/EventBufferNotice'
import clsx from 'clsx'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'
import { isEventsQuery, isHogQlAggregation, isHogQLQuery, isPersonsNode, taxonomicFilterToHogQl } from '~/queries/utils'
import { PersonPropertyFilters } from '~/queries/nodes/PersonsNode/PersonPropertyFilters'
import { PersonsSearch } from '~/queries/nodes/PersonsNode/PersonsSearch'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { extractExpressionComment, removeExpressionComment } from '~/queries/nodes/DataTable/utils'
import { InsightEmptyState, InsightErrorState } from 'scenes/insights/EmptyStates'
import { EventType } from '~/types'
import { SavedQueries } from '~/queries/nodes/DataTable/SavedQueries'
import { HogQLQueryEditor } from '~/queries/nodes/HogQLQuery/HogQLQueryEditor'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    /** Custom table columns */
    context?: QueryContext
}

const groupTypes = [
    TaxonomicFilterGroupType.HogQLExpression,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

let uniqueNode = 0

export function DataTable({ query, setQuery, context }: DataTableProps): JSX.Element {
    const [key] = useState(() => `DataTable.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const builtDataNodeLogic = dataNodeLogic(dataNodeLogicProps)

    const {
        response,
        responseLoading,
        responseError,
        canLoadNextData,
        canLoadNewData,
        nextDataLoading,
        newDataLoading,
        highlightedRows,
    } = useValues(builtDataNodeLogic)

    const dataTableLogicProps: DataTableLogicProps = { query, key }
    const { dataTableRows, columnsInQuery, columnsInResponse, queryWithDefaults, canSort } = useValues(
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
        showSavedQueries,
        showEventsBufferWarning,
        expandable,
    } = queryWithDefaults

    const actionsColumnShown = showActions && isEventsQuery(query.source) && columnsInResponse?.includes('*')
    const columnsInLemonTable = isHogQLQuery(query.source) ? columnsInResponse ?? columnsInQuery : columnsInQuery
    const lemonColumns: LemonTableColumn<DataTableRow, any>[] = [
        ...columnsInLemonTable.map((key, index) => ({
            dataIndex: key as any,
            ...renderColumnMeta(key, query, context),
            render: function RenderDataTableColumn(_: any, { result, label }: DataTableRow) {
                if (label) {
                    if (index === (expandable ? 1 : 0)) {
                        return {
                            children: label,
                            props: { colSpan: columnsInLemonTable.length + (actionsColumnShown ? 1 : 0) },
                        }
                    } else {
                        return { props: { colSpan: 0 } }
                    }
                } else if (result) {
                    if (isEventsQuery(query.source) || isHogQLQuery(query.source)) {
                        return renderColumn(key, result[index], result, query, setQuery, context)
                    }
                    return renderColumn(key, result[key], result, query, setQuery, context)
                }
            },
            sorter: undefined, // using custom sorting code
            more:
                showActions && isEventsQuery(query.source) ? (
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
                            renderValue={() => <>Edit column</>}
                            onChange={(v, g) => {
                                const hogQl = taxonomicFilterToHogQl(g, v)
                                if (hogQl && isEventsQuery(query.source)) {
                                    const isAggregation = isHogQlAggregation(hogQl)
                                    const isOrderBy = query.source?.orderBy?.[0] === key
                                    const isDescOrderBy = query.source?.orderBy?.[0] === `${key} DESC`
                                    setQuery?.({
                                        ...query,
                                        source: {
                                            ...query.source,
                                            select: query.source.select
                                                .map((s, i) => (i === index ? hogQl : s))
                                                .filter((c) => (isAggregation ? c !== '*' : true)),
                                            orderBy:
                                                isOrderBy || isDescOrderBy
                                                    ? [isDescOrderBy ? `${hogQl} DESC` : hogQl]
                                                    : query.source?.orderBy,
                                        },
                                    })
                                }
                            }}
                            groupTypes={groupTypes}
                            buttonProps={{ type: undefined }}
                        />
                        <LemonDivider />
                        {canSort ? (
                            <>
                                <LemonButton
                                    fullWidth
                                    status={query.source?.orderBy?.[0] === key ? 'primary' : 'stealth'}
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
                                    status={query.source?.orderBy?.[0] === `${key} DESC` ? 'primary' : 'stealth'}
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
                            placeholder={<span className="not-italic">Add column left</span>}
                            data-attr="datatable-add-column-left"
                            onChange={(v, g) => {
                                const hogQl = taxonomicFilterToHogQl(g, v)
                                if (hogQl && isEventsQuery(query.source)) {
                                    const isAggregation = isHogQlAggregation(hogQl)
                                    setQuery?.({
                                        ...query,
                                        source: {
                                            ...query.source,
                                            select: [
                                                ...(query.source.select || []).slice(0, index),
                                                hogQl,
                                                ...(query.source.select || []).slice(index),
                                            ].filter((c) => (isAggregation ? c !== '*' : true)),
                                        } as EventsQuery,
                                    })
                                }
                            }}
                            groupTypes={groupTypes}
                            buttonProps={{ type: undefined }}
                        />
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value={''}
                            placeholder={<span className="not-italic">Add column right</span>}
                            data-attr="datatable-add-column-right"
                            onChange={(v, g) => {
                                const hogQl = taxonomicFilterToHogQl(g, v)
                                if (hogQl && isEventsQuery(query.source)) {
                                    const isAggregation = isHogQlAggregation(hogQl)
                                    setQuery?.({
                                        ...query,
                                        source: {
                                            ...query.source,
                                            select: [
                                                ...(query.source.select || []).slice(0, index + 1),
                                                hogQl,
                                                ...(query.source.select || []).slice(index + 1),
                                            ].filter((c) => (isAggregation ? c !== '*' : true)),
                                        } as EventsQuery,
                                    })
                                }
                            }}
                            groupTypes={groupTypes}
                            buttonProps={{ type: undefined }}
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
        ...(actionsColumnShown
            ? [
                  {
                      dataIndex: '__more' as any,
                      title: '',
                      render: function RenderMore(_: any, { label, result }: DataTableRow) {
                          if (label) {
                              return { props: { colSpan: 0 } }
                          }
                          if (result && isEventsQuery(query.source) && columnsInResponse?.includes('*')) {
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
        (source: EventsNode | EventsQuery | PersonsNode | HogQLQuery) => setQuery?.({ ...query, source }),
        [setQuery]
    )

    const firstRowLeft = [
        showDateRange && isEventsQuery(query.source) ? (
            <DateRange query={query.source} setQuery={setQuerySource} />
        ) : null,
        showEventFilter && isEventsQuery(query.source) ? (
            <EventName query={query.source} setQuery={setQuerySource} />
        ) : null,
        showSearch && isPersonsNode(query.source) ? (
            <PersonsSearch query={query.source} setQuery={setQuerySource} />
        ) : null,
        showPropertyFilter && isEventsQuery(query.source) ? (
            <EventPropertyFilters query={query.source} setQuery={setQuerySource} />
        ) : null,
        showPropertyFilter && isPersonsNode(query.source) ? (
            <PersonPropertyFilters query={query.source} setQuery={setQuerySource} />
        ) : null,
    ].filter((x) => !!x)

    const firstRowRight = [
        showSavedQueries && isEventsQuery(query.source) ? <SavedQueries query={query} setQuery={setQuery} /> : null,
    ].filter((x) => !!x)

    const secondRowLeft = [
        showReload ? canLoadNewData ? <AutoLoad /> : <Reload /> : null,
        showElapsedTime ? <ElapsedTime /> : null,
    ].filter((x) => !!x)

    const secondRowRight = [
        showColumnConfigurator && isEventsQuery(query.source) ? (
            <ColumnConfigurator query={query} setQuery={setQuery} />
        ) : null,
        showExport ? <DataTableExport query={query} setQuery={setQuery} /> : null,
    ].filter((x) => !!x)

    const showFirstRow = firstRowLeft.length > 0 || firstRowRight.length > 0
    const showSecondRow = secondRowLeft.length > 0 || secondRowRight.length > 0
    const inlineEditorButtonOnRow = showFirstRow ? 1 : showSecondRow ? 2 : 0

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="relative w-full h-full space-y-4">
                    {showHogQLEditor && isHogQLQuery(query.source) ? (
                        <HogQLQueryEditor query={query.source} setQuery={setQuerySource} />
                    ) : null}
                    {showFirstRow && (
                        <div className="flex gap-4 items-center">
                            {firstRowLeft}
                            <div className="flex-1" />
                            {firstRowRight}
                            {inlineEditorButtonOnRow === 1 ? (
                                <InlineEditorButton query={query} setQuery={setQuery as (node: Node) => void} />
                            ) : null}
                        </div>
                    )}
                    {showFirstRow && showSecondRow && <LemonDivider />}
                    {showSecondRow && (
                        <div className="flex gap-4 items-center">
                            {secondRowLeft}
                            <div className="flex-1" />
                            {secondRowRight}
                            {inlineEditorButtonOnRow === 2 ? (
                                <InlineEditorButton query={query} setQuery={setQuery as (node: Node) => void} />
                            ) : null}
                        </div>
                    )}
                    {showEventsBufferWarning && isEventsQuery(query.source) && (
                        <EventBufferNotice additionalInfo=" - this helps ensure accuracy of insights grouped by unique users" />
                    )}
                    {inlineEditorButtonOnRow === 0 ? (
                        <div className="absolute right-0 z-10 p-1">
                            <InlineEditorButton query={query} setQuery={setQuery as (node: Node) => void} />
                        </div>
                    ) : null}
                    <LemonTable
                        className="DataTable"
                        loading={responseLoading && !nextDataLoading && !newDataLoading}
                        columns={lemonColumns}
                        key={
                            [...(columnsInResponse ?? []), ...columnsInQuery].join(
                                '::'
                            ) /* Bust the LemonTable cache when columns change */
                        }
                        dataSource={(dataTableRows ?? []) as DataTableRow[]}
                        rowKey={({ result }: DataTableRow, rowIndex) => {
                            if (result) {
                                if (isEventsQuery(query.source)) {
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
                                isHogQLQuery(query.source) ? (
                                    <InsightErrorState
                                        excludeDetail
                                        title={
                                            response && 'error' in response ? (response as any).error : responseError
                                        }
                                    />
                                ) : (
                                    <InsightErrorState />
                                )
                            ) : (
                                <InsightEmptyState />
                            )
                        }
                        expandable={
                            expandable && isEventsQuery(query.source) && columnsInResponse?.includes('*')
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
                                  }
                                : undefined
                        }
                        rowClassName={({ result, label }) =>
                            clsx('DataTable__row', {
                                'DataTable__row--highlight_once': result && highlightedRows.has(result),
                                'DataTable__row--category_row': !!label,
                            })
                        }
                    />
                    {canLoadNextData && ((response as any).results.length > 0 || !responseLoading) && (
                        <LoadNext query={query.source} />
                    )}
                    {/* TODO: this doesn't seem like the right solution... */}
                    <SessionPlayerModal />
                    <PersonDeleteModal />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
