import { DataTableColumn, DataTableNode, DataTableStringColumn, EventsNode } from '~/queries/schema'
import { useState } from 'react'
import { useValues, BindLogic } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/dataNodeLogic'
import { LemonTable, LemonTableColumn } from 'lib/components/LemonTable'
import { EventType, PropertyFilterType } from '~/types'
import { EventName } from '~/queries/nodes/EventsNode/EventName'
import { EventPropertyFilters } from '~/queries/nodes/EventsNode/EventPropertyFilters'
import { EventDetails } from 'scenes/events'
import { EventActions } from '~/queries/nodes/DataTable/EventActions'
import { DataTableExport } from '~/queries/nodes/DataTable/DataTableExport'
import { Reload } from '~/queries/nodes/DataTable/Reload'
import { LoadNext } from '~/queries/nodes/DataTable/LoadNext'
import { renderTitle } from '~/queries/nodes/DataTable/renderTitle'
import { renderColumn } from '~/queries/nodes/DataTable/renderColumn'
import { AutoLoad } from '~/queries/nodes/DataTable/AutoLoad'

interface DataTableProps {
    query: DataTableNode
    setQuery?: (node: DataTableNode) => void
}

export const defaultDataTableStringColumns: DataTableStringColumn[] = [
    'meta.event',
    'person',
    'event.$current_url',
    'person.email',
    'meta.timestamp',
]
export const defaultDataTableColumns: DataTableColumn[] = normalizeDataTableColumns(defaultDataTableStringColumns)

let uniqueNode = 0

export function DataTable({ query, setQuery }: DataTableProps): JSX.Element {
    const columns = query.columns ? normalizeDataTableColumns(query.columns) : defaultDataTableColumns
    const showPropertyFilter = query.showPropertyFilter ?? true
    const showEventFilter = query.showEventFilter ?? true
    const showActions = query.showActions ?? true
    const showExport = query.showExport ?? true
    const showReload = query.showReload ?? true
    const expandable = query.expandable ?? true

    const [id] = useState(() => uniqueNode++)
    const dataNodeLogicProps = { query: query.source, key: `DataTable.${id}` }
    const logic = dataNodeLogic(dataNodeLogicProps)
    const { response, responseLoading, canLoadNextData, canLoadNewData, nextDataLoading, newDataLoading } =
        useValues(logic)

    const dataSource = (response as null | EventsNode['response'])?.results ?? []

    const lemonColumns: LemonTableColumn<EventType, keyof EventType | undefined>[] = [
        ...columns.map(({ type, key }) => ({
            dataIndex: `${type}.${key}` as any,
            title: renderTitle(type, key),
            render: function RenderDataTableColumn(_: any, record: EventType) {
                return renderColumn(type, key, record)
            },
        })),
        ...(showActions
            ? [
                  {
                      dataIndex: 'more' as any,
                      title: '',
                      render: function RenderMore(_: any, record: EventType) {
                          return <EventActions event={record} />
                      },
                  },
              ]
            : []),
    ]

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            {(showPropertyFilter || showEventFilter || showExport) && (
                <div className="flex space-x-4 mb-4">
                    {showReload && (canLoadNewData ? <AutoLoad /> : <Reload />)}
                    {showEventFilter && (
                        <EventName query={query.source} setQuery={(source) => setQuery?.({ ...query, source })} />
                    )}
                    {showPropertyFilter && (
                        <EventPropertyFilters
                            query={query.source}
                            setQuery={(source) => setQuery?.({ ...query, source })}
                        />
                    )}
                    {showExport && <DataTableExport query={query} setQuery={setQuery} />}
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
    )
}

function normalizeDataTableColumns(input: (DataTableStringColumn | DataTableColumn)[]): DataTableColumn[] {
    return input.map((column) => {
        if (typeof column === 'string') {
            const [first, ...rest] = column.split('.')
            return {
                type: first as PropertyFilterType,
                key: rest.join('.'),
            }
        }
        return column
    })
}
