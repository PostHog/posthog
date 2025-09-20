import './FilterRow.scss'

import clsx from 'clsx'
import React, { useState } from 'react'

import { IconPlusSmall, IconTrash, IconX } from '@posthog/icons'

import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

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
    editable: boolean
    size?: 'xsmall' | 'small' | 'medium'
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
    editable,
    size = 'small',
}: FilterRowProps) {
    const [open, setOpen] = useState(() => openOnInsert)

    const { key } = item
    const isValid = isValidPropertyFilter(item)

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValid && !item.key) {
            onRemove(index)
        }

        setOpen(visible)
    }

    return (
        <>
            <div
                className={clsx(
                    'property-filter-row flex items-center flex-nowrap deprecated-space-x-2 max-w-full grow',
                    {
                        'sm:grow-0': isValid,
                        'wrap-filters': !disablePopover,
                    }
                )}
                data-attr={'property-filter-' + index}
            >
                {disablePopover ? (
                    <>
                        {filterComponent(() => setOpen(false))}
                        {Object.keys(filters[index]).length > 0 && editable ? (
                            <LemonButton
                                icon={orFiltering ? <IconTrash /> : <IconX />}
                                onClick={() => onRemove(index)}
                                size={size}
                                className="ml-2"
                                noPadding
                            />
                        ) : null}
                    </>
                ) : (
                    <Popover
                        className="filter-row-popover"
                        visible={open}
                        onClickOutside={() => handleVisibleChange(false)}
                        overlay={filterComponent(() => setOpen(false))}
                    >
                        {isValid ? (
                            <PropertyFilterButton
                                onClick={() => setOpen(!open)}
                                onClose={() => onRemove(index)}
                                item={item}
                                disabledReason={disabledReason}
                            />
                        ) : !disabledReason ? (
                            <LemonButton
                                onClick={() => setOpen(!open)}
                                className="new-prop-filter grow"
                                data-attr={'new-prop-filter-' + pageKey}
                                type="secondary"
                                size={size}
                                icon={<IconPlusSmall />}
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
