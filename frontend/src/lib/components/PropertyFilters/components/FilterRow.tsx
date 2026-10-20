import './FilterRow.scss'

import clsx from 'clsx'
import React, { useState } from 'react'

import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Popover } from 'lib/lemon-ui/Popover/Popover'

import { PathCleaningFilter, PropertyFilterRow } from '~/types'

import { LemonAddFilterButton } from './LemonAddFilterButton'
import { LemonFilterRowRemoveButton } from './LemonFilterRowRemoveButton'
import { OperandTag } from './OperandTag'
import { PropertyFilterButton } from './PropertyFilterButton'
import { QuillAddFilterButton } from './QuillAddFilterButton'
import { QuillFilterRowRemoveButton } from './QuillFilterRowRemoveButton'

interface FilterRowProps {
    item: Record<string, any>
    index: number
    filters: PropertyFilterRow[] | PathCleaningFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    filterComponent: (onComplete: () => void) => JSX.Element
    label: string
    labelClassName?: string
    openOnInsert?: boolean
    onRemove: (index: number) => void
    showRemoveButton?: boolean
    orFiltering?: boolean
    errorMessage?: JSX.Element | null
    disabledReason?: string
    editable: boolean
    size?: 'xsmall' | 'small' | 'medium'
    suffix?: JSX.Element | null
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
    showRemoveButton = true,
    orFiltering,
    errorMessage,
    disabledReason,
    editable,
    size = 'small',
    suffix,
}: FilterRowProps) {
    const [open, setOpen] = useState(() => openOnInsert)
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')

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
                className={clsx('property-filter-row flex items-center max-w-full', {
                    'flex-wrap gap-2': !!suffix,
                    'flex-nowrap deprecated-space-x-2': !suffix,
                    'grow sm:grow-0': isValid,
                    'grow-0': !isValid,
                    'wrap-filters': !disablePopover,
                    'property-filter-row--with-suffix': !!suffix,
                })}
                data-attr={'property-filter-' + index}
            >
                {disablePopover ? (
                    <>
                        {filterComponent(() => setOpen(false))}
                        {Object.keys(filters[index]).length > 0 && editable && showRemoveButton ? (
                            quillEnabled ? (
                                <QuillFilterRowRemoveButton
                                    orFiltering={orFiltering}
                                    onRemove={() => onRemove(index)}
                                />
                            ) : (
                                <LemonFilterRowRemoveButton
                                    orFiltering={orFiltering}
                                    onRemove={() => onRemove(index)}
                                    size={size}
                                />
                            )
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
                            quillEnabled ? (
                                <QuillAddFilterButton
                                    label={label}
                                    labelClassName={labelClassName}
                                    pageKey={pageKey}
                                    open={open}
                                    onClick={() => setOpen(!open)}
                                />
                            ) : (
                                <LemonAddFilterButton
                                    label={label}
                                    labelClassName={labelClassName}
                                    pageKey={pageKey}
                                    size={size}
                                    onClick={() => setOpen(!open)}
                                />
                            )
                        ) : undefined}
                    </Popover>
                )}
                {key && showConditionBadge && index + 1 < totalCount && <OperandTag operand="and" />}
                {suffix}
            </div>
            {errorMessage}
        </>
    )
})
