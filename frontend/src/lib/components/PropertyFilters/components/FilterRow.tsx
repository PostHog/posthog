import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { AnyPropertyFilter, PropertyFilter as PropertyFilterType } from '~/types'
import { Button } from 'antd'
import { useActions } from 'kea'
import { Popover, Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton from './PropertyFilterButton'
import 'scenes/actions/Actions.scss'
import { TooltipPlacement } from 'antd/lib/tooltip'
import { propertyFilterLogic } from 'lib/components/PropertyFilters/propertyFilterLogic'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'

interface FilterRowProps {
    item: AnyPropertyFilter
    index: number
    filters: AnyPropertyFilter[]
    pageKey: string
    showConditionBadge?: boolean
    totalCount: number
    disablePopover?: boolean
    popoverPlacement?: TooltipPlacement | null
}

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    pageKey,
    showConditionBadge,
    totalCount,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement,
}: FilterRowProps) {
    const { remove } = useActions(propertyFilterLogic)
    const [open, setOpen] = useState(false)

    const { key } = item

    const handleVisibleChange = (visible: boolean): void => {
        if (!visible && isValidPropertyFilter(item) && !item.key) {
            remove(index)
        }
        setOpen(visible)
    }

    const propertyFilterCommonProps = {
        key: index,
        index,
        onComplete: () => setOpen(false),
        selectProps: {},
    }

    return (
        <Row
            align="middle"
            className="mt-05 mb-05"
            data-attr={'property-filter-' + index}
            style={{
                maxWidth: '90vw',
                margin: '0.25rem 0',
                padding: '0.25rem 0',
            }}
            wrap={false}
        >
            {disablePopover ? (
                <>
                    <PropertyFilter {...propertyFilterCommonProps} variant="unified" />
                    {!!Object.keys(filters[index]).length && (
                        <CloseButton
                            onClick={() => remove(index)}
                            style={{ cursor: 'pointer', float: 'none', paddingLeft: 8 }}
                        />
                    )}
                </>
            ) : (
                <>
                    <Popover
                        trigger="click"
                        onVisibleChange={handleVisibleChange}
                        destroyTooltipOnHide={true}
                        defaultVisible={false}
                        visible={open}
                        placement={popoverPlacement || 'bottomLeft'}
                        getPopupContainer={(trigger) =>
                            // Prevent scrolling up on trigger
                            (trigger.parentNode as HTMLElement | undefined) ||
                            (document.querySelector('body') as HTMLElement)
                        }
                        content={
                            <PropertyFilter
                                {...propertyFilterCommonProps}
                                variant="tabs"
                                selectProps={{
                                    delayBeforeAutoOpen: 150,
                                    placement: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                }}
                            />
                        }
                    >
                        {isValidPropertyFilter(item) ? (
                            <PropertyFilterButton
                                onClick={() => setOpen(!open)}
                                item={item as PropertyFilterType /* not EmptyPropertyFilter */}
                            />
                        ) : (
                            <Button type="default" shape="round" data-attr={'new-prop-filter-' + pageKey}>
                                Add filter
                            </Button>
                        )}
                    </Popover>
                    {!!Object.keys(filters[index]).length && (
                        <CloseButton
                            className="ml-1"
                            onClick={() => remove(index)}
                            style={{ cursor: 'pointer', float: 'none', marginLeft: 5 }}
                        />
                    )}
                </>
            )}
            {key && showConditionBadge && index + 1 < totalCount && (
                <span style={{ marginLeft: 16, right: 16, position: 'absolute' }} className="stateful-badge and">
                    AND
                </span>
            )}
        </Row>
    )
})
