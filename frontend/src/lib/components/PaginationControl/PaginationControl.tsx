import React from 'react'
import { IconChevronLeft, IconChevronRight } from '../icons'
import { LemonButton } from '../LemonButton'
import './PaginationControl.scss'
import { PaginationState } from './types'

export interface PaginationControlProps<T> extends PaginationState<T> {
    nouns?: [string, string]
}

export function PaginationControl<T>({
    pagination,
    currentPage,
    setCurrentPage,
    pageCount,
    dataSourcePage,
    entryCount,
    currentStartIndex,
    currentEndIndex,
    nouns = ['entry', 'entries'],
}: PaginationControlProps<T>): JSX.Element | null {
    /** Whether pages previous and next are available. */
    const isPreviousAvailable: boolean =
        currentPage !== null ? currentPage > 1 : !!(pagination?.controlled && pagination.onBackward)
    const isNextAvailable: boolean =
        currentPage !== null && pageCount !== null
            ? currentPage < pageCount
            : !!(pagination?.controlled && pagination.onForward)
    /** Whether there's reason to show pagination. */
    const showPagination: boolean = isPreviousAvailable || isNextAvailable || pagination?.hideOnSinglePage === false

    const currentPageSize = dataSourcePage.length

    return showPagination ? (
        <div className="PaginationControl">
            <span>
                {currentPageSize === 0
                    ? `No ${nouns[1]}`
                    : entryCount === null
                    ? `${currentPageSize} ${currentPageSize === 1 ? nouns[0] : nouns[1]} on this page`
                    : currentPageSize === 1
                    ? `${currentEndIndex} of ${entryCount} ${entryCount === 1 ? nouns[0] : nouns[1]}`
                    : `${currentStartIndex + 1}-${currentEndIndex} of ${entryCount} ${nouns[1]}`}
            </span>
            <LemonButton
                icon={<IconChevronLeft />}
                type="stealth"
                disabled={!isPreviousAvailable}
                onClick={() => {
                    pagination?.controlled && pagination.onBackward?.()
                    if ((pagination?.controlled && currentPage) || !pagination?.controlled) {
                        setCurrentPage(Math.max(1, Math.min(pageCount as number, currentPage as number) - 1))
                    }
                }}
            />
            <LemonButton
                icon={<IconChevronRight />}
                type="stealth"
                disabled={!isNextAvailable}
                onClick={() => {
                    pagination?.controlled && pagination.onForward?.()
                    if ((pagination?.controlled && currentPage) || !pagination?.controlled) {
                        setCurrentPage(Math.min(pageCount as number, (currentPage as number) + 1))
                    }
                }}
            />
        </div>
    ) : null
}
