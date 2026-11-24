import { LogicWrapper, useActions, useValues } from 'kea'
import { ReactNode, useMemo } from 'react'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { AnyPropertyFilter } from '~/types'

import { EntityDrawerHost } from '../shared/EntityDrawerHost'
import { shellScopeLogic } from '../shell/shellScopeLogic'
import { TraceDrawerHost } from '../trace/TraceDrawerHost'
import { traceDrawerLogic } from '../trace/traceDrawerLogic'
import { TRACE_DRAWER_OPEN_ROW_CLASS } from '../trace/traceDrawerRows'
import { TraceDrawerRowsSync } from '../trace/TraceDrawerRowsHost'
import { TraceListRow } from '../trace/traceListRows'
import { ListEmptyState } from './components/ListEmptyState'
import { ListErrorState } from './components/ListErrorState'
import { ListTable } from './components/ListTable'
import { ListToolbar } from './components/ListToolbar'
import type { EntityListLogicType } from './entityListLogic'
import type { FacetKey } from './facetFilters'
import { ListFiltersHost } from './ListFiltersHost'
import { ListFiltersLogicProps, listFiltersLogic } from './listFiltersLogic'

export interface EntityDetailContext<Detail> {
    key: string
    /** Null while loading. */
    detail: Detail | null
    labels: string[]
    /** The trace and step open in the trace drawer, to mark their example. */
    openTraceId: string | null
    openStepId: string | null
    openTrace: (row: TraceListRow) => void
    propertyFilters: AnyPropertyFilter[]
    setPropertyFilters: (filters: AnyPropertyFilter[]) => void
}

export interface EntityListHostProps<Row extends Record<string, any>, Detail> {
    logic: LogicWrapper<EntityListLogicType<Row, Detail>>
    filters: ListFiltersLogicProps & { listId: 'errors' | 'tools' | 'people' }
    columns: (labels: string[]) => LemonTableColumns<Row>
    rowKey: (row: Row) => string
    searchPlaceholder: string
    facetControls: readonly FacetKey[]
    /** Singular and lowercase: "error". */
    noun: string
    drawerTitle: (key: string) => ReactNode
    /** The rows the trace drawer steps through, from the open row's examples. */
    traceRows: (key: string, detail: Detail) => TraceListRow[]
    renderDetail: (context: EntityDetailContext<Detail>) => ReactNode
    emptyState: { title: string; description: string }
    emptyFilteredTitle: string
    errorTitle: string
    'data-attr': string
}

export function EntityListHost<Row extends Record<string, any>, Detail>({
    logic,
    filters: filtersProps,
    columns: columnsOf,
    rowKey,
    searchPlaceholder,
    facetControls,
    noun,
    drawerTitle,
    traceRows: traceRowsOf,
    renderDetail,
    emptyState,
    emptyFilteredTitle,
    errorTitle,
    'data-attr': dataAttr,
}: EntityListHostProps<Row, Detail>): JSX.Element {
    const {
        rows,
        state,
        rowsLoading,
        buckets,
        filterTestAccounts,
        selectedKey,
        selectedIndex,
        previousKey,
        nextKey,
        detail,
        detailFailed,
    } = useValues(logic)
    const { select, reload, loadDetail } = useActions(logic)
    const filtersLogic = listFiltersLogic(filtersProps)
    const { filters, searchDraft } = useValues(filtersLogic)
    const { setPropertyFilters, setFilterTestAccounts, setSearchDraft, resetFilters } = useActions(filtersLogic)
    const { dateFrom, dateTo } = useValues(shellScopeLogic)
    const { setDateRange } = useActions(shellScopeLogic)
    const listId = filtersProps.listId
    const { openRef } = useValues(traceDrawerLogic({ listId }))
    const { openRow } = useActions(traceDrawerLogic({ listId }))

    const columns = useMemo(() => columnsOf(buckets.labels), [columnsOf, buckets.labels])
    const traceRows = useMemo(
        () => (selectedKey && detail ? traceRowsOf(selectedKey, detail) : []),
        [detail, selectedKey, traceRowsOf]
    )

    return (
        <div className="flex flex-col gap-3">
            <ListToolbar
                search={searchDraft}
                onSearchChange={setSearchDraft}
                searchPlaceholder={searchPlaceholder}
                filters={
                    <ListFiltersHost
                        propertyFilters={filters.propertyFilters}
                        onChange={setPropertyFilters}
                        controls={facetControls}
                        pageKey={dataAttr}
                        data-attr={dataAttr}
                    />
                }
                testAccounts={
                    <TestAccountFilterSwitch
                        checked={filterTestAccounts}
                        onChange={setFilterTestAccounts}
                        size="small"
                    />
                }
                dateRange={<DateFilter dateFrom={dateFrom} dateTo={dateTo} onChange={setDateRange} size="small" />}
                onReload={reload}
                reloading={rowsLoading}
                data-attr={dataAttr}
            />
            <ListTable<Row>
                state={state}
                columns={columns}
                rows={rows ?? []}
                rowKey={rowKey}
                refreshing={rowsLoading && state === 'ready'}
                onRow={(row) => ({
                    onClick: () => select(rowKey(row)),
                    className: rowKey(row) === selectedKey ? TRACE_DRAWER_OPEN_ROW_CLASS : 'cursor-pointer',
                })}
                emptyState={<ListEmptyState title={emptyState.title} description={emptyState.description} />}
                emptyFilteredState={
                    <ListEmptyState
                        title={emptyFilteredTitle}
                        description="Change or clear the filters to see more."
                        action={{
                            label: 'Clear filters',
                            onClick: resetFilters,
                            'data-attr': `${dataAttr}-clear-filters`,
                        }}
                    />
                }
                errorState={
                    <ListErrorState
                        title={errorTitle}
                        description="Try again, or pick a shorter date range."
                        retry={{ onClick: reload, 'data-attr': `${dataAttr}-retry` }}
                    />
                }
                data-attr={dataAttr}
            />
            {selectedKey ? (
                <EntityDrawerHost
                    noun={noun}
                    title={drawerTitle(selectedKey)}
                    position={selectedIndex >= 0 && rows ? { index: selectedIndex, total: rows.length } : null}
                    onPrevious={previousKey ? () => select(previousKey) : null}
                    onNext={nextKey ? () => select(nextKey) : null}
                    onClose={() => select(null)}
                    traceListId={listId}
                    data-attr={`${dataAttr}-drawer`}
                >
                    {detailFailed ? (
                        <ListErrorState
                            title={`Could not load this ${noun}`}
                            description="Try again, or pick a shorter date range."
                            retry={{ onClick: loadDetail, 'data-attr': `${dataAttr}-drawer-retry` }}
                        />
                    ) : (
                        renderDetail({
                            key: selectedKey,
                            detail,
                            labels: buckets.labels,
                            openTraceId: openRef?.traceId ?? null,
                            openStepId: openRef?.stepId ?? null,
                            openTrace: openRow,
                            propertyFilters: filters.propertyFilters,
                            setPropertyFilters,
                        })
                    )}
                </EntityDrawerHost>
            ) : null}
            <TraceDrawerRowsSync listId={listId} rows={traceRows} />
            <TraceDrawerHost listId={listId} />
        </div>
    )
}
