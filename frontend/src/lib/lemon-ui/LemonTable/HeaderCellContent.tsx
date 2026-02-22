import clsx from 'clsx'

import { IconInfo } from '@posthog/icons'

import { LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { IconWithCount } from 'lib/lemon-ui/icons'

import { Tooltip } from '../Tooltip'
import { determineColumnKey } from './columnUtils'
import { Sorting, SortingIndicator, getNextSorting } from './sorting'
import { LemonTableColumn } from './types'

export interface HeaderCellContentProps {
    column: LemonTableColumn<any, any>
    currentSorting: Sorting | null
    disableSortingCancellation: boolean
    hideSortingIndicatorWhenInactive: boolean
    maxHeaderWidth?: string
    setLocalSorting: (sorting: Sorting | null) => void
}

export function HeaderCellContent({
    column,
    currentSorting,
    disableSortingCancellation,
    hideSortingIndicatorWhenInactive,
    maxHeaderWidth,
    setLocalSorting,
}: HeaderCellContentProps): JSX.Element {
    return (
        <div
            className="LemonTable__header-content"
            /* eslint-disable-next-line react/forbid-dom-props */
            style={{
                justifyContent:
                    column.align === 'center' ? 'center' : column.align === 'right' ? 'flex-end' : 'flex-start',
            }}
            onClick={
                column.sorter
                    ? (event) => {
                          const target = event.target as HTMLElement
                          if (
                              target.closest('.LemonCheckbox') ||
                              target.classList.contains('LemonCheckbox__box') ||
                              target.tagName.toLowerCase() === 'label' ||
                              target.tagName.toLowerCase() === 'input' ||
                              target.closest('[data-attr="table-header-more"]')
                          ) {
                              return
                          }
                          const nextSorting = getNextSorting(
                              currentSorting,
                              determineColumnKey(column, 'sorting'),
                              disableSortingCancellation
                          )
                          setLocalSorting(nextSorting)
                      }
                    : undefined
            }
        >
            <div
                className={clsx('flex items-center', column?.fullWidth && 'w-full', column.sorter && 'cursor-pointer')}
                /* eslint-disable-next-line react/forbid-dom-props */
                style={maxHeaderWidth ? { maxWidth: maxHeaderWidth } : undefined}
            >
                {column.tooltip ? (
                    <Tooltip title={column.tooltip}>
                        <div className="flex items-center">
                            {column.title}
                            <IconInfo className="ml-1 text-base" />
                        </div>
                    </Tooltip>
                ) : (
                    column.title
                )}
                {column.sorter &&
                    (() => {
                        const columnKey = determineColumnKey(column, 'sorting')
                        const isActiveSort = currentSorting?.columnKey === columnKey
                        const order = isActiveSort ? currentSorting.order : null
                        if (hideSortingIndicatorWhenInactive && !isActiveSort) {
                            return null
                        }
                        return (
                            <Tooltip
                                title={() => {
                                    const nextSorting = getNextSorting(
                                        currentSorting,
                                        columnKey,
                                        disableSortingCancellation
                                    )
                                    return `Click to ${
                                        nextSorting
                                            ? nextSorting.order === 1
                                                ? 'sort ascending'
                                                : 'sort descending'
                                            : 'cancel sorting'
                                    }`
                                }}
                            >
                                <SortingIndicator order={order} />
                            </Tooltip>
                        )
                    })()}
            </div>
            {column.more &&
                (column.moreIcon ? (
                    <LemonButtonWithDropdown
                        aria-label="more"
                        data-attr="table-header-more"
                        icon={
                            column.moreFilterCount !== undefined && column.moreFilterCount > 0 ? (
                                <IconWithCount count={column.moreFilterCount} showZero={false} status="danger">
                                    {column.moreIcon}
                                </IconWithCount>
                            ) : (
                                column.moreIcon
                            )
                        }
                        dropdown={{
                            placement: 'bottom-end',
                            actionable: true,
                            overlay: column.more,
                        }}
                        size="small"
                        className="ml-1"
                    />
                ) : (
                    <More overlay={column.more} className="ml-1" data-attr="table-header-more" />
                ))}
        </div>
    )
}
