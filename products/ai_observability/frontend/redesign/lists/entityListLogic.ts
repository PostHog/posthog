import { Logic, LogicWrapper, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'

import { shellScopeLogic } from '../shell/shellScopeLogic'
import { currentUrlWith, rawSearchParam } from '../trace/rawSearchParam'
import type { ListTableState } from './components/ListTable'
import { ListFilters, listFiltersLogic } from './listFiltersLogic'
import { ListScope, VolumeBuckets, volumeBuckets } from './listQuery'

export interface EntityListConfig<Row, Detail> {
    listId: 'errors' | 'tools' | 'people'
    /** The list's route. The logic reads and writes the URL only there. */
    path: string
    /** The URL param holding the open row's key. */
    param: string
    rowKey: (row: Row) => string
    loadRows: (scope: ListScope, buckets: VolumeBuckets, search: string) => Promise<Row[]>
    loadDetail: (key: string, scope: ListScope, buckets: VolumeBuckets) => Promise<Detail>
}

export interface EntityListValues<Row, Detail> {
    filters: ListFilters
    dateFrom: string
    dateTo: string | null
    filterTestAccounts: boolean
    scope: ListScope
    buckets: VolumeBuckets
    rows: Row[] | null
    rowsLoading: boolean
    rowsFailed: boolean
    state: ListTableState
    selectedKey: string | null
    selectedIndex: number
    previousKey: string | null
    nextKey: string | null
    detail: Detail | null
    detailFailed: boolean
    loadedDetailLoading: boolean
}

export interface EntityListActions {
    loadRows: () => void
    loadDetail: () => void
    select: (key: string | null) => void
    setSelectedKey: (key: string | null) => void
    reload: () => void
}

export interface EntityListLogicType<Row, Detail> extends Logic {
    values: EntityListValues<Row, Detail>
    actions: EntityListActions
}

// ponytail: one logic shape for the three lists; split it when one of them needs paging or server sorting.
export function entityListLogic<Row, Detail>(
    config: EntityListConfig<Row, Detail>
): LogicWrapper<EntityListLogicType<Row, Detail>> {
    const listFilters = listFiltersLogic({ listId: config.listId, path: config.path })

    // kea-typegen can't type a generic factory, so the builders stay untyped and the wrapper carries the type
    return kea<any>([
        path(['products', 'ai_observability', 'frontend', 'redesign', 'lists', 'entityListLogic', config.listId]),
        connect(() => ({
            values: [
                listFilters,
                ['filters'],
                shellScopeLogic,
                ['dateFrom', 'dateTo'],
                filterTestAccountsDefaultsLogic,
                ['filterTestAccountsDefault'],
            ],
        })),
        actions<any>({
            select: (key: string | null) => ({ key }),
            setSelectedKey: (key: string | null) => ({ key }),
            reload: true,
        }),
        loaders(({ values }) => ({
            rows: [
                null as Row[] | null,
                {
                    loadRows: async (_, breakpoint) => {
                        await breakpoint(10)
                        const rows = await config.loadRows(values.scope, values.buckets, values.filters.search)
                        breakpoint()
                        return rows
                    },
                },
            ],
            loadedDetail: [
                null as { key: string; detail: Detail } | null,
                {
                    loadDetail: async (_, breakpoint) => {
                        const key = values.selectedKey
                        if (key === null) {
                            return null
                        }
                        await breakpoint(10)
                        const detail = await config.loadDetail(key, values.scope, values.buckets)
                        breakpoint()
                        return { key, detail }
                    },
                },
            ],
        })),
        reducers({
            selectedKey: [null as string | null, { setSelectedKey: (_, { key }) => key }],
            rowsFailed: [false, { loadRows: () => false, loadRowsSuccess: () => false, loadRowsFailure: () => true }],
            detailFailed: [
                false,
                { loadDetail: () => false, loadDetailSuccess: () => false, loadDetailFailure: () => true },
            ],
        }),
        selectors({
            filterTestAccounts: [
                (s) => [s.filters, s.filterTestAccountsDefault],
                (filters: ListFilters, fallback: boolean): boolean => filters.filterTestAccounts ?? fallback,
            ],
            scope: [
                (s) => [s.filters, s.dateFrom, s.dateTo, s.filterTestAccounts],
                (
                    filters: ListFilters,
                    dateFrom: string,
                    dateTo: string | null,
                    filterTestAccounts: boolean
                ): ListScope => ({
                    propertyFilters: filters.propertyFilters,
                    filterTestAccounts,
                    dateFrom,
                    dateTo,
                }),
            ],
            buckets: [
                (s) => [s.dateFrom, s.dateTo],
                (dateFrom: string, dateTo: string | null): VolumeBuckets => volumeBuckets(dateFrom, dateTo),
            ],
            state: [
                (s) => [s.rows, s.rowsLoading, s.rowsFailed, s.filters],
                (rows: Row[] | null, loading: boolean, failed: boolean, filters: ListFilters): ListTableState =>
                    failed
                        ? 'error'
                        : rows === null || (loading && rows.length === 0)
                          ? 'loading'
                          : rows.length > 0
                            ? 'ready'
                            : filters.propertyFilters.length > 0 || filters.search
                              ? 'empty-filtered'
                              : 'empty',
            ],
            selectedIndex: [
                (s) => [s.rows, s.selectedKey],
                (rows: Row[] | null, key: string | null): number =>
                    key === null ? -1 : (rows ?? []).findIndex((row) => config.rowKey(row) === key),
            ],
            previousKey: [
                (s) => [s.rows, s.selectedIndex],
                (rows: Row[] | null, index: number): string | null =>
                    rows && index > 0 ? config.rowKey(rows[index - 1]) : null,
            ],
            // A detail loaded for another row never shows, so switching rows shows the loading state at once.
            detail: [
                (s) => [s.loadedDetail, s.selectedKey],
                (loaded: { key: string; detail: Detail } | null, key: string | null): Detail | null =>
                    loaded && loaded.key === key ? loaded.detail : null,
            ],
            nextKey: [
                (s) => [s.rows, s.selectedIndex],
                (rows: Row[] | null, index: number): string | null =>
                    rows && index >= 0 && index < rows.length - 1 ? config.rowKey(rows[index + 1]) : null,
            ],
        }),
        listeners(({ actions, values }) => ({
            reload: () => {
                actions.loadRows()
                actions.loadDetail()
            },
            select: ({ key }) => {
                if (key === values.selectedKey) {
                    return
                }
                actions.setSelectedKey(key)
                // Switching rows closes a trace opened from the previous row's examples.
                router.actions.push(
                    ...currentUrlWith(router.values, {
                        [config.param]: key ?? undefined,
                        trace: undefined,
                        ts: undefined,
                        step: undefined,
                    })
                )
            },
            setSelectedKey: () => actions.loadDetail(),
        })),
        subscriptions(({ actions }) => ({
            scope: (scope: ListScope, previous: ListScope | undefined) => {
                if (previous === undefined || JSON.stringify(scope) !== JSON.stringify(previous)) {
                    actions.loadRows()
                    actions.loadDetail()
                }
            },
            filters: (filters: ListFilters, previous: ListFilters | undefined) => {
                if (previous && filters.search !== previous.search) {
                    actions.loadRows()
                }
            },
        })),
        urlToAction(({ actions, values }) => ({
            [config.path]: (_, __, ___, { search }) => {
                const key = rawSearchParam(search, config.param)
                if (key !== values.selectedKey) {
                    actions.setSelectedKey(key)
                }
            },
        })),
    ]) as LogicWrapper<EntityListLogicType<Row, Detail>>
}
