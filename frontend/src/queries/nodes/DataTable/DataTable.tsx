import './DataTable.scss'
import { AnyResponseType, DataTableNode, EventsQuery, QueryContext } from '~/queries/schema'
import { useState } from 'react'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
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
    uniqueKey?: string | number
    query: DataTableNode
    setQuery?: (query: DataTableNode) => void
    /** Custom table columns */
    context?: QueryContext
    /* Cached Results are provided when shared or exported,
    the data node logic becomes read only implicitly */
    cachedResults?: AnyResponseType
}

const groupTypes = [
    TaxonomicFilterGroupType.HogQLExpression,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.EventFeatureFlags,
]

let uniqueNode = 0

const DataTable = ({
    uniqueKey,
    query,
    setQuery,
    context,
    cachedResults,
    children,
}: DataTableProps & { children?: React.ReactNode }): JSX.Element => {
    const [key] = useState(() => `DataTable.${uniqueKey || uniqueNode++}`)

    const dataNodeLogicProps: DataNodeLogicProps = { query: query.source, key, cachedResults: cachedResults }
    const builtDataNodeLogic = dataNodeLogic(dataNodeLogicProps)

    const { canLoadNewData } = useValues(builtDataNodeLogic)

    const dataTableLogicProps: DataTableLogicProps = { query, setQuery, key, context }
    const { queryWithDefaults } = useValues(dataTableLogic(dataTableLogicProps))
    const { setQuerySource } = useActions(dataTableLogic(dataTableLogicProps))

    const {
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
        showOpenEditorButton,
    } = queryWithDefaults

    const isReadOnly = setQuery === undefined

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
        showReload ? <Reload key="reload" /> : null,
        showReload && canLoadNewData ? <AutoLoad key="auto-load" /> : null,
        showElapsedTime ? <ElapsedTime key="elapsed-time" /> : null,
    ].filter((x) => !!x)

    const secondRowRight = [
        (showColumnConfigurator || showPersistentColumnConfigurator) && isEventsQuery(query.source) ? (
            <ColumnConfigurator key="column-configurator" query={query} setQuery={setQuery} />
        ) : null,
        showExport ? <DataTableExport key="data-table-export" query={query} setQuery={setQuery} /> : null,
    ].filter((x) => !!x)

    const showFirstRow = !isReadOnly && (firstRowLeft.length > 0 || firstRowRight.length > 0)
    const showSecondRow = !isReadOnly && (secondRowLeft.length > 0 || secondRowRight.length > 0)
    const inlineEditorButtonOnRow = showFirstRow ? 1 : showSecondRow ? 2 : 0

    return (
        <BindLogic logic={dataTableLogic} props={dataTableLogicProps}>
            <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
                <div className="relative w-full flex flex-col gap-4 flex-1 overflow-hidden">
                    {children ? (
                        children
                    ) : (
                        <>
                            {showHogQLEditor && isHogQLQuery(query.source) && !isReadOnly ? (
                                <HogQLQueryEditor query={query.source} setQuery={setQuerySource} />
                            ) : null}
                            {showFirstRow && (
                                <div className="flex gap-4 items-center">
                                    {firstRowLeft}
                                    <div className="flex-1" />
                                    {firstRowRight}
                                    {showOpenEditorButton && inlineEditorButtonOnRow === 1 && !isReadOnly ? (
                                        <OpenEditorButton query={query} />
                                    ) : null}
                                </div>
                            )}
                            {showFirstRow && showSecondRow && <LemonDivider className="my-0" />}
                            {showSecondRow && (
                                <div className="flex gap-4 items-center">
                                    {secondRowLeft}
                                    <div className="flex-1" />
                                    {secondRowRight}
                                    {showOpenEditorButton && inlineEditorButtonOnRow === 2 && !isReadOnly ? (
                                        <OpenEditorButton query={query} />
                                    ) : null}
                                </div>
                            )}
                            {showOpenEditorButton && inlineEditorButtonOnRow === 0 && !isReadOnly ? (
                                <div className="absolute right-0 z-10 p-1">
                                    <OpenEditorButton query={query} />
                                </div>
                            ) : null}
                            <ResultsTable isReadOnly={isReadOnly} />
                        </>
                    )}
                    {/* TODO: this doesn't seem like the right solution... */}
                    <SessionPlayerModal />
                    <PersonDeleteModal />
                </div>
            </BindLogic>
        </BindLogic>
    )
}

const HogQLEditor = (): JSX.Element | null => {
    const { query } = useValues(dataTableLogic)
    const { setQuerySource } = useActions(dataTableLogic)

    return isHogQLQuery(query.source) ? <HogQLQueryEditor query={query.source} setQuery={setQuerySource} /> : null
}

const ResultsTable = ({ isReadOnly }: { isReadOnly: boolean }): JSX.Element => {
    const {
        response,
        responseLoading,
        responseError,
        queryCancelled,
        canLoadNextData,
        nextDataLoading,
        newDataLoading,
        highlightedRows,
    } = useValues(dataNodeLogic)
    const logic = useMountedLogic(dataTableLogic)
    const { dataTableRows, columnsInQuery, columnsInResponse, queryWithDefaults, canSort } = useValues(logic)
    const { setQuery } = useActions(logic)

    const { showActions, expandable, embedded } = queryWithDefaults
    const { query, context } = logic.props

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
                !isReadOnly && showActions && isEventsQuery(query.source) ? (
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
                            type="tertiary"
                            fullWidth
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
                            type="tertiary"
                            fullWidth
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
                        />
                        <TaxonomicPopover
                            groupType={TaxonomicFilterGroupType.HogQLExpression}
                            value={''}
                            placeholder={<span className="not-italic">Add column right</span>}
                            data-attr="datatable-add-column-right"
                            type="tertiary"
                            fullWidth
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

    return (
        <LemonTable
            className="DataTable"
            loading={responseLoading && !nextDataLoading && !newDataLoading}
            columns={lemonColumns}
            key={
                [...(columnsInResponse ?? []), ...columnsInQuery].join(
                    '::'
                ) /* Bust the LemonTable cache when columns change */
            }
            embedded={embedded}
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
                    isHogQLQuery(query.source) || isEventsQuery(query.source) ? (
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
                    <InsightEmptyState heading={context?.emptyStateHeading} detail={context?.emptyStateDetail} />
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
                          expandedRowClassName: ({ result }) => {
                              const record = Array.isArray(result) ? result[0] : result
                              return record && record['event'] === '$exception'
                                  ? 'border border-danger-dark bg-danger-highlight'
                                  : null
                          },
                      }
                    : undefined
            }
            rowClassName={({ result, label }) =>
                clsx('DataTable__row', {
                    'DataTable__row--highlight_once': result && highlightedRows.has(result),
                    'DataTable__row--category_row': !!label,
                    'border border-danger-dark bg-danger-highlight':
                        result && result[0] && result[0]['event'] === '$exception',
                })
            }
            footer={
                canLoadNextData &&
                ((response as any).results.length > 0 || !responseLoading) && <LoadNext query={query.source} />
            }
        />
    )
}

DataTable.Results = ResultsTable
DataTable.HogQLQueryEditor = HogQLEditor
export default DataTable
