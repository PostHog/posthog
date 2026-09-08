import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useCallback, useMemo, useState } from 'react'

import { PaginationAuto, PaginationManual, PaginationState } from './types'

export function usePagination<T>(
    dataSource: T[],
    pagination: PaginationAuto | PaginationManual | undefined,
    id?: string
): PaginationState<T> {
    /** Search param that will be used for storing and syncing the current page */
    const currentPageParam = id ? `${id}_page` : 'page'

    const { location, searchParams, hashParams } = useValues(router)
    const { push } = useActions(router)
    const [localCurrentPage, setLocalCurrentPage] = useState(1)

    const syncPageToUrl = pagination?.useUrl !== false
    const setCurrentPage = useCallback(
        (newPage: number) => {
            if (syncPageToUrl) {
                push(location.pathname, { ...searchParams, [currentPageParam]: newPage }, hashParams)
            } else {
                setLocalCurrentPage(newPage)
            }
        },
        [location, searchParams, hashParams, push, syncPageToUrl] // oxlint-disable-line react-hooks/exhaustive-deps
    )

    const entryCount: number | null = pagination?.controlled ? pagination.entryCount || null : dataSource.length
    const pageCount: number | null =
        entryCount && (pagination ? (pagination.pageSize ? Math.ceil(entryCount / pagination.pageSize) : 1) : null)
    const currentPage: number | null = pagination?.controlled
        ? pagination.currentPage || null
        : Math.min(
              syncPageToUrl ? parseInt(searchParams[currentPageParam]) || 1 : localCurrentPage,
              pageCount as number
          )

    const { dataSourcePage, currentStartIndex, currentEndIndex } = useMemo(() => {
        const calculatedStartIndex =
            pagination && currentPage && pagination.pageSize ? (currentPage - 1) * pagination.pageSize : 0
        const processedDataSource =
            pagination && !pagination.controlled
                ? dataSource.slice(calculatedStartIndex, calculatedStartIndex + pagination.pageSize)
                : dataSource
        const calculatedEndIndex = calculatedStartIndex + processedDataSource.length
        return {
            dataSourcePage: processedDataSource,
            currentStartIndex: calculatedStartIndex,
            currentEndIndex: calculatedEndIndex,
        }
    }, [currentPage, pageCount, pagination, dataSource])

    return {
        pagination,
        dataSourcePage,
        currentPage,
        pageCount,
        currentStartIndex,
        currentEndIndex,
        entryCount,
        setCurrentPage,
    }
}
