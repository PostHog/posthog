import React, { useState } from 'react'
import { AnyPropertyFilter, PathCleaningFilter } from '~/types'
import { Row } from 'antd'
import { PropertyFilterButton } from './PropertyFilterButton'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import './FilterRow.scss'
import clsx from 'clsx'
import { IconClose, IconDelete, IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

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
    onRemove: (index: number) => void
    orFiltering?: boolean
    errorMessage?: JSX.Element | null
}

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    pageKey,
    showConditionBadge,
    totalCount,
    disablePopover = false, // use bare PropertyFilter without popover
    filterComponent,
    label,
    onRemove,
    orFiltering,
    errorMessage,
}: FilterRowProps) {
    const [open, setOpen] = useState(false)

    const { key } = item

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValidPropertyFilter(item) && !item.key) {
            onRemove(index)
        }
        setOpen(visible)
    }

    return (
        <>
            <Row
                align="middle"
                className={clsx('property-filter-row', !disablePopover && 'wrap-filters')}
                data-attr={'property-filter-' + index}
                wrap={false}
            >
                {disablePopover ? (
                    <>
                        {filterComponent(() => setOpen(false))}
                        {!!Object.keys(filters[index]).length && (
                            <LemonButton
                                icon={orFiltering ? <IconDelete /> : <IconClose />}
                                status="primary-alt"
                                onClick={() => onRemove(index)}
                                size="small"
                                className="ml-2"
                                noPadding
                            />
                        )}
                    </>
                ) : (
                    <Popover
                        className={'filter-row-popover'}
                        visible={open}
                        onClickOutside={() => handleVisibleChange(false)}
                        overlay={filterComponent(() => setOpen(false))}
                    >
                        {isValidPropertyFilter(item) ? (
                            <PropertyFilterButton
                                onClick={() => setOpen(!open)}
                                onClose={() => onRemove(index)}
                                item={item}
                            />
                        ) : (
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
                        )}
                    </Popover>
                )}
                {key && showConditionBadge && index + 1 < totalCount && (
                    <span style={{ marginLeft: 16, right: 16, position: 'absolute' }} className="stateful-badge and">
                        AND
                    </span>
                )}
            </Row>
            {errorMessage}
        </>
    )
})
