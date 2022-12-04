import './DataTable.scss'
import { DataTableNode, EventsNode } from '~/queries/schema'
import { useState } from 'react'
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
import { renderTitle } from '~/queries/nodes/DataTable/renderTitle'
import { renderColumn } from '~/queries/nodes/DataTable/renderColumn'
import { AutoLoad } from '~/queries/nodes/DataNode/AutoLoad'
import { dataTableLogic, DataTableLogicProps } from '~/queries/nodes/DataTable/dataTableLogic'
import { ColumnConfigurator } from '~/queries/nodes/DataTable/ColumnConfigurator/ColumnConfigurator'
import { teamLogic } from 'scenes/teamLogic'
import { defaultDataTableStringColumns } from '~/queries/nodes/DataTable/defaults'
import { LemonDivider } from 'lib/components/LemonDivider'
import { EventBufferNotice } from 'scenes/events/EventBufferNotice'
import clsx from 'clsx'
import { SessionPlayerModal } from 'scenes/session-recordings/player/modal/SessionPlayerModal'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
}

let uniqueNode = 0

export function DataTable({ query, setQuery }: DataTableProps): JSX.Element {
    const [id] = useState(() => uniqueNode++)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key: `DataTable.${id}` }
    const {
        response,
        responseLoading,
        canLoadNextData,
        canLoadNewData,
        nextDataLoading,
        newDataLoading,
        highlightedRows,
    } = useValues(dataNodeLogic(dataNodeLogicProps))

    const { currentTeam } = useValues(teamLogic)
    const defaultColumns = currentTeam?.live_events_columns ?? defaultDataTableStringColumns

    const dataTableLogicProps: DataTableLogicProps = { query: query, key: `DataTable.${id}`, defaultColumns }
    const { columns, queryWithDefaults } = useValues(dataTableLogic(dataTableLogicProps))

    const {
        showActions,
        showEventFilter,
        showPropertyFilter,
        showReload,
        showExport,
        showColumnConfigurator,
        showEventsBufferWarning,
        expandable,
    } = queryWithDefaults

    const lemonColumns: LemonTableColumn<EventType, keyof EventType | undefined>[] = [
        ...columns.map((key) => ({
            dataIndex: key as any,
            title: renderTitle(key),
            render: function RenderDataTableColumn(_: any, record: EventType) {
                return renderColumn(key, record, query, setQuery)
            },
        })),
        ...(showActions
            ? [
                  {
                      dataIndex: 'more' as any,
                      title: '',
                      render: function RenderMore(_: any, record: EventType) {
                          return <EventRowActions event={record} />
                      },
                  },
              ]
            : []),
    ]
    const dataSource = (response as null | EventsNode['response'])?.results ?? []
    const setQuerySource = (source: EventsNode): void => setQuery?.({ ...query, source })

    const showFilters = showEventFilter || showPropertyFilter
    const showTools = showReload || showExport || showColumnConfigurator

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                {showFilters && (
                    <div className="flex space-x-4 mb-4">
                        {showEventFilter && <EventName query={query.source} setQuery={setQuerySource} />}
                        {showPropertyFilter && <EventPropertyFilters query={query.source} setQuery={setQuerySource} />}
                    </div>
                )}
                {showFilters && showTools ? (
                    <div className="my-4">
                        <LemonDivider />
                    </div>
                ) : null}
                {showTools && (
                    <div className="flex space-x-4 mb-4">
                        <div className="flex-1">{showReload && (canLoadNewData ? <AutoLoad /> : <Reload />)}</div>
                        {showColumnConfigurator && <ColumnConfigurator query={query} setQuery={setQuery} />}
                        {showExport && <DataTableExport query={query} setQuery={setQuery} />}
                    </div>
                )}
                {showEventsBufferWarning && (
                    <EventBufferNotice
                        additionalInfo=" - this helps ensure accuracy of insights grouped by unique users"
                        className="mb-4"
                    />
                )}
                <LemonTable
                    className="DataTable"
                    loading={responseLoading && !nextDataLoading && !newDataLoading}
                    columns={lemonColumns}
                    dataSource={dataSource}
                    expandable={
                        expandable
                            ? {
                                  expandedRowRender: function renderExpand(event) {
                                      return event && <EventDetails event={event} />
                                  },
                                  rowExpandable: () => true,
                                  noIndent: true,
                              }
                            : undefined
                    }
                    rowKey={(row) => row.id ?? undefined}
                    rowClassName={(row) =>
                        clsx('DataTable__row', { 'DataTable__row--highlight_once': highlightedRows[row?.id] })
                    }
                />
                {canLoadNextData && ((response as any).results.length > 0 || !responseLoading) && <LoadNext />}
                <SessionPlayerModal />
            </BindLogic>
        </BindLogic>
    )
}
