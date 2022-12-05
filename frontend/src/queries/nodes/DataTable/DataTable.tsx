import './DataTable.scss'
import { DataTableNode, EventsNode, Node, PersonsNode, QueryCustom } from '~/queries/schema'
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
import { InlineEditor } from '~/queries/nodes/Node/InlineEditor'
import { isEventsNode, isPersonsNode } from '~/queries/utils'
import { PersonPropertyFilters } from '~/queries/nodes/PersonsNode/PersonPropertyFilters'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
    /** Custom table columns */
    custom?: QueryCustom
}

let uniqueNode = 0

export function DataTable({ query, setQuery, custom }: DataTableProps): JSX.Element {
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

    const { currentTeam } = useValues(teamLogic)
    const defaultColumns = currentTeam?.live_events_columns ?? defaultDataTableStringColumns

    const dataTableLogicProps: DataTableLogicProps = { query, key, defaultColumns }
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
            title: renderTitle(key, custom),
            render: function RenderDataTableColumn(_: any, record: EventType) {
                return renderColumn(key, record, query, setQuery, custom)
            },
        })),
        ...(showActions && isEventsNode(query.source)
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
    const setQuerySource = (source: EventsNode | PersonsNode): void => setQuery?.({ ...query, source })

    const showFilters = showEventFilter || showPropertyFilter
    const showTools = showReload || showExport || showColumnConfigurator
    const inlineRow = showFilters ? 1 : showTools ? 2 : 0

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="space-y-4 relative">
                    {showFilters && (
                        <div className="flex gap-4">
                            {showEventFilter && isEventsNode(query.source) && (
                                <EventName query={query.source} setQuery={setQuerySource} />
                            )}
                            {showPropertyFilter && isEventsNode(query.source) && (
                                <EventPropertyFilters query={query.source} setQuery={setQuerySource} />
                            )}
                            {showPropertyFilter && isPersonsNode(query.source) && (
                                <PersonPropertyFilters query={query.source} setQuery={setQuerySource} />
                            )}
                            {inlineRow === 1 ? (
                                <>
                                    <div className="flex-1" />
                                    <InlineEditor
                                        query={queryWithDefaults}
                                        setQuery={setQuery as (node: Node) => void}
                                    />
                                </>
                            ) : null}
                        </div>
                    )}
                    {showFilters && showTools && <LemonDivider />}
                    {showTools && (
                        <div className="flex gap-4">
                            <div className="flex-1">{showReload && (canLoadNewData ? <AutoLoad /> : <Reload />)}</div>
                            {showColumnConfigurator && isEventsNode(query.source) && (
                                <ColumnConfigurator query={query} setQuery={setQuery} />
                            )}
                            {showExport && <DataTableExport query={query} setQuery={setQuery} />}
                            {inlineRow === 2 ? (
                                <InlineEditor query={queryWithDefaults} setQuery={setQuery as (node: Node) => void} />
                            ) : null}
                        </div>
                    )}
                    {showEventsBufferWarning && isEventsNode(query.source) && (
                        <EventBufferNotice additionalInfo=" - this helps ensure accuracy of insights grouped by unique users" />
                    )}
                    {inlineRow === 0 ? (
                        <div className="absolute right-0 z-10 p-1">
                            <InlineEditor query={queryWithDefaults} setQuery={setQuery as (node: Node) => void} />
                        </div>
                    ) : null}
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
                </div>
            </BindLogic>
        </BindLogic>
    )
}
