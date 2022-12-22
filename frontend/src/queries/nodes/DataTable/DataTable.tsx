import './DataTable.scss'
import { DataTableNode, EventsNode, EventsQuery, Node, PersonsNode, QueryContext } from '~/queries/schema'
import { useCallback, useState } from 'react'
import { useValues, BindLogic } from 'kea'
import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { LemonTable, LemonTableColumn } from 'lib/components/LemonTable'
import { EventType } from '~/types'
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
import { dataTableLogic, DataTableLogicProps } from '~/queries/nodes/DataTable/dataTableLogic'
import { ColumnConfigurator } from '~/queries/nodes/DataTable/ColumnConfigurator/ColumnConfigurator'
import { LemonDivider } from 'lib/components/LemonDivider'
import { EventBufferNotice } from 'scenes/events/EventBufferNotice'
import clsx from 'clsx'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'
import { InlineEditorButton } from '~/queries/nodes/Node/InlineEditorButton'
import { isEventsQuery, isPersonsNode } from '~/queries/utils'
import { PersonPropertyFilters } from '~/queries/nodes/PersonsNode/PersonPropertyFilters'
import { PersonsSearch } from '~/queries/nodes/PersonsNode/PersonsSearch'
import { PersonDeleteModal } from 'scenes/persons/PersonDeleteModal'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    /** Custom table columns */
    context?: QueryContext
}

let uniqueNode = 0

export function DataTable({ query, setQuery, context }: DataTableProps): JSX.Element {
    const [key] = useState(() => `DataTable.${uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key }
    const {
        response,
        responseLoading,
        canLoadNextData,
        canLoadNewData,
        nextDataLoading,
        newDataLoading,
        highlightedRows,
    } = useValues(dataNodeLogic(dataNodeLogicProps))

    const dataTableLogicProps: DataTableLogicProps = { query, key }
    const {
        columns: columnsFromQuery,
        queryWithDefaults,
        canSort,
        sorting,
    } = useValues(dataTableLogic(dataTableLogicProps))

    const {
        showActions,
        showSearch,
        showEventFilter,
        showPropertyFilter,
        showReload,
        showExport,
        showColumnConfigurator,
        showEventsBufferWarning,
        expandable,
    } = queryWithDefaults

    const columnsInResponse: string[] | null =
        response?.columns && Array.isArray(response.columns) && !response.columns.find((c) => typeof c !== 'string')
            ? (response?.columns as string[])
            : null

    const columns: string[] = columnsInResponse ?? columnsFromQuery
    const lemonColumns: LemonTableColumn<EventType, keyof EventType | undefined>[] = [
        ...columns.map((key, index) => ({
            dataIndex: key as any,
            ...renderColumnMeta(key, query, context),
            render: function RenderDataTableColumn(_: any, record: EventType) {
                if (isEventsQuery(query.source)) {
                    return renderColumn(key, record[index], record, query, setQuery, context)
                }
                return renderColumn(key, record[key], record, query, setQuery, context)
            },
            sorter: canSort || undefined, // we sort on the backend
        })),
        ...(showActions && isEventsQuery(query.source) && columns.includes('*')
            ? [
                  {
                      dataIndex: '__more' as any,
                      title: '',
                      render: function RenderMore(_: any, record: EventType | any[]) {
                          if (isEventsQuery(query.source) && columns.includes('*')) {
                              return <EventRowActions event={record[columns.indexOf('*')]} />
                          }
                          return <EventRowActions event={record as EventType} />
                      },
                      width: 0,
                  },
              ]
            : []),
    ].filter((column) => !query.hiddenColumns?.includes(column.dataIndex) && column.dataIndex !== '*')

    const dataSource =
        (response as null | EventsNode['response'] | EventsQuery['response'] | PersonsNode['response'])?.results ?? []
    const setQuerySource = useCallback(
        (source: EventsNode | EventsQuery | PersonsNode) => setQuery?.({ ...query, source }),
        [setQuery]
    )

    const firstRow = [
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

    const secondRowLeft = [showReload ? canLoadNewData ? <AutoLoad /> : <Reload /> : null].filter((x) => !!x)

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
                        <div className="flex gap-4">
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
                        <div className="flex gap-4">
                            <div className="flex-1">{secondRowLeft}</div>
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
                        rowKey={(record) => {
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
                        sorting={canSort && setQuery ? sorting : undefined}
                        useURLForSorting={false}
                        onSort={
                            canSort && setQuery
                                ? (newSorting) =>
                                      setQuery?.({
                                          ...query,
                                          source: {
                                              ...query.source,
                                              orderBy: newSorting
                                                  ? [(newSorting.order === -1 ? '-' : '') + newSorting.columnKey]
                                                  : undefined,
                                          } as EventsNode,
                                      } as DataTableNode)
                                : undefined
                        }
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
                                      rowExpandable: () => true,
                                      noIndent: true,
                                  }
                                : undefined
                        }
                        rowClassName={(row) =>
                            clsx('DataTable__row', {
                                'DataTable__row--highlight_once': row && highlightedRows.has(row),
                            })
                        }
                    />
                    {canLoadNextData && ((response as any).results.length > 0 || !responseLoading) && <LoadNext />}
                    {/* TODO: this doesn't seem like the right solution... */}
                    <SessionPlayerModal />
                    <PersonDeleteModal />
                </div>
            </BindLogic>
        </BindLogic>
    )
}
