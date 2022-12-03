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

interface DataTableProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
}

let uniqueNode = 0

export function DataTable({ query, setQuery }: DataTableProps): JSX.Element {
    const showPropertyFilter = query.showPropertyFilter ?? true
    const showEventFilter = query.showEventFilter ?? true
    const showActions = query.showActions ?? true
    const showExport = query.showExport ?? true
    const showReload = query.showReload ?? true
    const showColumnConfigurator = query.showColumnConfigurator ?? true
    const expandable = query.expandable ?? true

    const [id] = useState(() => uniqueNode++)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key: `DataTable.${id}` }
    const { response, responseLoading, canLoadNextData, canLoadNewData, nextDataLoading, newDataLoading } = useValues(
        dataNodeLogic(dataNodeLogicProps)
    )

    const { currentTeam } = useValues(teamLogic)
    const defaultColumns = currentTeam?.live_events_columns ?? defaultDataTableStringColumns

    const dataTableLogicProps: DataTableLogicProps = { query: query, key: `DataTable.${id}`, defaultColumns }
    const { columns } = useValues(dataTableLogic(dataTableLogicProps))

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

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                {(showReload || showEventFilter || showPropertyFilter || showExport || showColumnConfigurator) && (
                    <div className="flex space-x-4 mb-4">
                        {showReload && (canLoadNewData ? <AutoLoad /> : <Reload />)}
                        {showEventFilter && <EventName query={query.source} setQuery={setQuerySource} />}
                        {showPropertyFilter && <EventPropertyFilters query={query.source} setQuery={setQuerySource} />}
                        {showExport && <DataTableExport query={query} setQuery={setQuery} />}
                        {showColumnConfigurator && <ColumnConfigurator query={query} setQuery={setQuery} />}
                    </div>
                )}
                <LemonTable
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
                />
                {canLoadNextData && ((response as any).results.length > 0 || !responseLoading) && <LoadNext />}
            </BindLogic>
        </BindLogic>
    )
}
