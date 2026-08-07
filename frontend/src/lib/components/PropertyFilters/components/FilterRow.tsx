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
    labelClassName?: string
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
    labelClassName = '',
    onRemove,
    orFiltering,
    errorMessage,
    disabledReason,
    editable,
    size = 'small',
}: FilterRowProps) {
    const [open, setOpen] = useState(() => openOnInsert)
    // True while the popover is opening but floating-ui hasn't positioned it yet, so it's still
    // invisible. Clicking the trigger during this frame used to toggle `open` straight back off,
    // swallowing the click; we ignore trigger clicks until the overlay is actually on screen.
    const [openingPopover, setOpeningPopover] = useState(false)

    const { key } = item
    const isValid = isValidPropertyFilter(item)

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValid && !item.key) {
            onRemove(index)
        }

        setOpen(visible)
    }

    const toggleOpen = (): void => {
        if (openingPopover) {
            return
        }
        setOpen((wasOpen) => !wasOpen)
    }

    return (
        <>
            <div
                className={clsx('property-filter-row flex items-center flex-nowrap deprecated-space-x-2 max-w-full', {
                    'grow sm:grow-0': isValid,
                    'grow-0': !isValid,
                    'wrap-filters': !disablePopover,
                })}
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
                        onPositionPendingChange={setOpeningPopover}
                        overlay={filterComponent(() => setOpen(false))}
                    >
                        {isValid ? (
                            <PropertyFilterButton
                                onClick={toggleOpen}
                                onClose={() => onRemove(index)}
                                item={item}
                                disabledReason={disabledReason}
                            />
                        ) : !disabledReason ? (
                            <LemonButton
                                onClick={toggleOpen}
                                className={clsx('new-prop-filter', labelClassName)}
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
