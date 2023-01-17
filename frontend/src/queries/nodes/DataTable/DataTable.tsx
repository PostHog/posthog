import './DataTable.scss'
import { DataTableNode, EventsNode, EventsQuery, Node, PersonsNode, QueryContext } from '~/queries/schema'
import { useCallback, useState } from 'react'
import { BindLogic, useValues } from 'kea'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonTable, LemonTableColumn } from 'lib/components/LemonTable'
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
import { categoryRowKey, dataTableLogic, DataTableLogicProps } from '~/queries/nodes/DataTable/dataTableLogic'
import { ColumnConfigurator } from '~/queries/nodes/DataTable/ColumnConfigurator/ColumnConfigurator'
import { LemonDivider } from 'lib/components/LemonDivider'
import { EventBufferNotice } from 'scenes/events/EventBufferNotice'
import clsx from 'clsx'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'
import { isEventsQuery, isHogQlAggregation, isPersonsNode, taxonomicFilterToHogQl } from '~/queries/utils'
import { PersonPropertyFilters } from '~/queries/nodes/PersonsNode/PersonPropertyFilters'
import { PersonsSearch } from '~/queries/nodes/PersonsNode/PersonsSearch'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { DateRange } from '~/queries/nodes/DataNode/DateRange'
import { LemonButton } from 'lib/components/LemonButton'
import { TaxonomicPopup } from 'lib/components/TaxonomicPopup/TaxonomicPopup'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { extractExpressionComment, removeExpressionComment } from '~/queries/nodes/DataTable/utils'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    /** Custom table columns */
    context?: QueryContext
}

const groupTypes = [
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.HogQLExpression,
]

let uniqueNode = 0

export function DataTable({ query, setQuery, context }: DataTableProps): JSX.Element {
    const [key] = useState(() => `DataTable.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const builtDataNodeLogic = dataNodeLogic(dataNodeLogicProps)

    const {
        response,
        responseLoading,
        canLoadNextData,
        canLoadNewData,
        nextDataLoading,
        newDataLoading,
        highlightedRows,
    } = useValues(builtDataNodeLogic)

    const dataTableLogicProps: DataTableLogicProps = { query, key }
    const { resultsWithLabelRows, columnsInQuery, columnsInResponse, queryWithDefaults, canSort } = useValues(
        dataTableLogic(dataTableLogicProps)
    )

    const {
        showActions,
        showDateRange,
        showSearch,
        showEventFilter,
        showPropertyFilter,
        showReload,
        showExport,
        showElapsedTime,
        showColumnConfigurator,
        showEventsBufferWarning,
        expandable,
    } = queryWithDefaults

    const columns: string[] = columnsInResponse ?? columnsInQuery
    const actionsColumnShown = showActions && isEventsQuery(query.source) && columns.includes('*')
    const lemonColumns: LemonTableColumn<Record<string, any> | any[], any>[] = [
        ...columns.map(
            (key, index) =>
                ({
                    dataIndex: key as any,
                    ...renderColumnMeta(key, query, context),
                    render: function RenderDataTableColumn(_: any, record: Record<string, any> | any[]) {
                        if (categoryRowKey in record) {
                            if (index === (expandable ? 1 : 0)) {
                                return {
                                    children: record[categoryRowKey],
                                    props: { colSpan: columns.length + (actionsColumnShown ? 1 : 0) },
                                }
                            } else {
                                return { props: { colSpan: 0 } }
                            }
                        } else if (isEventsQuery(query.source)) {
                            return renderColumn(key, record[index], record, query, setQuery, context)
                        }
                        return renderColumn(key, record[key], record, query, setQuery, context)
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
                                <TaxonomicPopup
                                    groupType={TaxonomicFilterGroupType.HogQLExpression}
                                    value={key}
                                    renderValue={() => <>Edit column</>}
                                    onChange={(v, g) => {
                                        const hogQl = taxonomicFilterToHogQl(g, v)
                                        if (hogQl && isEventsQuery(query.source)) {
                                            const isAggregation = isHogQlAggregation(hogQl)
                                            const isOrderBy = query.source?.orderBy?.[0] === key
                                            const isDescOrderBy = query.source?.orderBy?.[0] === `-${key}`
                                            setQuery?.({
                                                ...query,
                                                source: {
                                                    ...query.source,
                                                    select: query.source.select
                                                        .map((s, i) => (i === index ? hogQl : s))
                                                        .filter((c) => (isAggregation ? c !== '*' : true)),
                                                    orderBy:
                                                        isOrderBy || isDescOrderBy
                                                            ? [isDescOrderBy ? `-${hogQl}` : hogQl]
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
                                            status={query.source?.orderBy?.[0] === `-${key}` ? 'primary' : 'stealth'}
                                            data-attr="datatable-sort-desc"
                                            onClick={() => {
                                                setQuery?.({
                                                    ...query,
                                                    source: {
                                                        ...query.source,
                                                        orderBy: [`-${key}`],
                                                    } as EventsQuery,
                                                })
                                            }}
                                        >
                                            Sort descending
                                        </LemonButton>
                                        <LemonDivider />
                                    </>
                                ) : null}
                                <TaxonomicPopup
                                    groupType={TaxonomicFilterGroupType.EventProperties}
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
                                <TaxonomicPopup
                                    groupType={TaxonomicFilterGroupType.EventProperties}
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
                                {columns.filter((c) => c !== '*').length > 1 ? (
                                    <>
                                        <LemonDivider />
                                        <LemonButton
                                            fullWidth
                                            status="danger"
                                            data-attr="datatable-remove-column"
                                            onClick={() => {
                                                setQuery?.({
                                                    ...query,
                                                    source: {
                                                        ...query.source,
                                                        select: (query.source as EventsQuery).select.filter(
                                                            (_, i) => i !== index
                                                        ),
                                                    } as EventsQuery,
                                                })
                                            }}
                                        >
                                            Remove column
                                        </LemonButton>
                                    </>
                                ) : null}
                            </>
                        ) : undefined,
                } as LemonTableColumn<Record<string, any> | any[], any>)
        ),
        ...(actionsColumnShown
            ? [
                  {
                      dataIndex: '__more' as any,
                      title: '',
                      render: function RenderMore(_: any, record: Record<string, any> | any[]) {
                          if (categoryRowKey in record) {
                              return { props: { colSpan: 0 } }
                          }
                          if (isEventsQuery(query.source) && columns.includes('*')) {
                              return <EventRowActions event={record[columns.indexOf('*')]} />
                          }
                          return null
                      },
                      width: 0,
                  },
              ]
            : []),
    ].filter((column) => !query.hiddenColumns?.includes(column.dataIndex) && column.dataIndex !== '*')

    const dataSource = resultsWithLabelRows ?? []

    const setQuerySource = useCallback(
        (source: EventsNode | EventsQuery | PersonsNode) => setQuery?.({ ...query, source }),
        [setQuery]
    )

    const firstRow = [
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

    const showFirstRow = firstRow.length > 0
    const showSecondRow = secondRowLeft.length > 0 || secondRowRight.length > 0
    const inlineEditorButtonOnRow = showFirstRow ? 1 : showSecondRow ? 2 : 0

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="space-y-4 relative">
                    {showFirstRow && (
                        <div className="flex gap-4 items-center">
                            {firstRow}
                            {inlineEditorButtonOnRow === 1 ? (
                                <>
                                    <div className="flex-1" />
                                    <InlineEditorButton query={query} setQuery={setQuery as (node: Node) => void} />
                                </>
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
                        key={columns.join('::') /* Bust the LemonTable cache when columns change */}
                        dataSource={dataSource}
                        rowKey={(record, rowIndex) => {
                            if (categoryRowKey in record) {
                                return `__category_row__${rowIndex}`
                            }
                            if (isEventsQuery(query.source)) {
                                if (columns.includes('*')) {
                                    return record[columns.indexOf('*')].uuid
                                } else if (columns.includes('uuid')) {
                                    return record[columns.indexOf('uuid')]
                                } else if (columns.includes('id')) {
                                    return record[columns.indexOf('id')]
                                }
                                return JSON.stringify(record)
                            } else {
                                return (
                                    ('uuid' in record ? (record as any).uuid : null) ??
                                    record.id ??
                                    JSON.stringify(record)
                                )
                            }
                        }}
                        sorting={null}
                        useURLForSorting={false}
                        expandable={
                            expandable && isEventsQuery(query.source) && columns.includes('*')
                                ? {
                                      expandedRowRender: function renderExpand(event) {
                                          if (isEventsQuery(query.source) && Array.isArray(event)) {
                                              return (
                                                  <EventDetails
                                                      event={event[columns.indexOf('*')] ?? {}}
                                                      useReactJsonView
                                                  />
                                              )
                                          }
                                          return event ? <EventDetails event={event} useReactJsonView /> : null
                                      },
                                      rowExpandable: (event) => !(categoryRowKey in event),
                                      noIndent: true,
                                  }
                                : undefined
                        }
                        rowClassName={(row) =>
                            clsx('DataTable__row', {
                                'DataTable__row--highlight_once': row && highlightedRows.has(row),
                                'DataTable__row--category_row': row && categoryRowKey in row,
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
