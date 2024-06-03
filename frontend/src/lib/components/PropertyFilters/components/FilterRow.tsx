import './FilterRow.scss'

import { IconPlus, IconTrash, IconX } from '@posthog/icons'
import clsx from 'clsx'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import React, { useEffect, useState } from 'react'

import { AnyPropertyFilter, PathCleaningFilter } from '~/types'

import { OperandTag } from './OperandTag'
import { PropertyFilterButton } from './PropertyFilterButton'

interface FilterRowProps {
    item: Record<string, any>
    index: number
    filters: AnyPropertyFilter[] | PathCleaningFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    filterComponent: (onComplete: () => void) => JSX.Element
    label: string
    openOnInsert?: boolean
    onRemove: (index: number) => void
    orFiltering?: boolean
    errorMessage?: JSX.Element | null
    disabledReason?: string
}

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    pageKey,
    showConditionBadge,
    totalCount,
    disablePopover = false, // use bare PropertyFilter without popover
    openOnInsert = false,
    filterComponent,
    label,
    onRemove,
    orFiltering,
    errorMessage,
    disabledReason,
}: FilterRowProps) {
    const [open, setOpen] = useState(false)

    useEffect(() => {
        setOpen(openOnInsert)
    }, [])

    const { key } = item

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValidPropertyFilter(item) && !item.key) {
            onRemove(index)
        }
        setOpen(visible)
    }

    return (
        <>
            <div
                className={clsx(
                    'property-filter-row flex items-center flex-nowrap space-x-2 max-w-full',
                    !disablePopover && 'wrap-filters'
                )}
                data-attr={'property-filter-' + index}
            >
                {disablePopover ? (
                    <>
                        {filterComponent(() => setOpen(false))}
                        {!!Object.keys(filters[index]).length && (
                            <LemonButton
                                icon={orFiltering ? <IconTrash /> : <IconX />}
                                onClick={() => onRemove(index)}
                                size="small"
                                className="ml-2"
                                noPadding
                            />
                        )}
                    </>
                ) : (
                    <Popover
                        className="filter-row-popover"
                        visible={open}
                        onClickOutside={() => handleVisibleChange(false)}
                        overlay={filterComponent(() => setOpen(false))}
                    >
                        {isValidPropertyFilter(item) ? (
                            <PropertyFilterButton
                                onClick={() => setOpen(!open)}
                                onClose={() => onRemove(index)}
                                item={item}
                                disabledReason={disabledReason}
                            />
                        ) : !disabledReason ? (
                            <LemonButton
                                onClick={() => setOpen(!open)}
                                className="new-prop-filter"
                                data-attr={'new-prop-filter-' + pageKey}
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                sideIcon={null}
                            >
                                {label}
                            </LemonButton>
                        ) : undefined}
                    </Popover>
                )}
                {key && showConditionBadge && index + 1 < totalCount && <OperandTag operand="and" />}
            </div>
            {errorMessage}
        </>
    )
})
