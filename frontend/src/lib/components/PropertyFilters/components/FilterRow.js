import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useActions } from 'kea'
import { Popover, Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton from './PropertyFilterButton'
import 'scenes/actions/Actions.scss'

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    logic,
    pageKey,
    showConditionBadge,
    totalCount,
    disablePopover = false, // use bare PropertyFilter without popover
    popoverPlacement,
}) {
    const { remove } = useActions(logic)
    let [open, setOpen] = useState(false)
    const { key } = item

    let handleVisibleChange = (visible) => {
        if (!visible && Object.keys(item).length >= 0 && !item[Object.keys(item)[0]]) {
            remove(index)
        }
        setOpen(visible)
    }

    const propertyFilterCommonProps = {
        key: index,
        index,
        onComplete: () => setOpen(false),
        logic,
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
                        getPopupContainer={(trigger) => trigger.parentNode} // Prevent scrolling up on trigger
                        content={
                            <PropertyFilter
                                {...propertyFilterCommonProps}
                                variant="tabs"
                                selectProps={{
                                    delayBeforeAutoOpen: 150,
                                    position: pageKey === 'trends-filters' ? 'bottomLeft' : undefined,
                                }}
                            />
                        }
                    >
                        {key ? (
                            <PropertyFilterButton onClick={() => setOpen(!open)} item={item} />
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
