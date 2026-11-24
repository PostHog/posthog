import { ReactNode } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { LemonTable, LemonTableColumns, LemonTableProps } from 'lib/lemon-ui/LemonTable'

export type ListTableState = 'loading' | 'ready' | 'empty' | 'empty-filtered' | 'error'

export interface ListTableProps<T extends Record<string, any>> {
    state: ListTableState
    columns: LemonTableColumns<T>
    rows: T[]
    rowKey: (row: T) => string
    refreshing: boolean
    onRow?: LemonTableProps<T>['onRow']
    onPrevious?: () => void
    onNext?: () => void
    emptyState: ReactNode
    emptyFilteredState: ReactNode
    errorState: ReactNode
    'data-attr': string
}

const SKELETON_ROWS = 8

export function ListTable<T extends Record<string, any>>({
    state,
    columns,
    rows,
    rowKey,
    refreshing,
    onRow,
    onPrevious,
    onNext,
    emptyState,
    emptyFilteredState,
    errorState,
    'data-attr': dataAttr,
}: ListTableProps<T>): JSX.Element {
    const pageLoadingReason = state === 'loading' || refreshing ? 'A page is loading' : undefined
    const stateContent: Partial<Record<ListTableState, ReactNode>> = {
        empty: emptyState,
        'empty-filtered': emptyFilteredState,
        error: errorState,
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonTable<T>
                columns={columns}
                dataSource={state === 'ready' ? rows : []}
                rowKey={rowKey}
                onRow={onRow}
                loading={state === 'loading' || refreshing}
                loadingSkeletonRows={SKELETON_ROWS}
                emptyState={stateContent[state]}
                useURLForSorting={false}
                data-attr={dataAttr}
            />
            {onPrevious || onNext ? (
                <div className="flex justify-end gap-2">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconChevronLeft />}
                        onClick={onPrevious}
                        disabledReason={pageLoadingReason ?? (onPrevious ? undefined : 'No previous page')}
                        aria-label="Previous page"
                        // pinned: autocapture dashboards and tests select the pager by this value
                        data-attr={`${dataAttr}-previous-page`}
                    >
                        Previous
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size="small"
                        sideIcon={<IconChevronRight />}
                        onClick={onNext}
                        disabledReason={pageLoadingReason ?? (onNext ? undefined : 'No next page')}
                        aria-label="Next page"
                        // pinned: autocapture dashboards and tests select the pager by this value
                        data-attr={`${dataAttr}-next-page`}
                    >
                        Next
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}
