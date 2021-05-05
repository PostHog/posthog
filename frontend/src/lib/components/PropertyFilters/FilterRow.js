import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useActions } from 'kea'
import { Popover, Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton from './PropertyFilterButton'
import '../../../scenes/actions/Actions.scss'

export const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    logic,
    pageKey,
    showConditionBadge,
    totalCount,
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

    return (
        <Row
            align="middle"
            className="mt-05 mb-05"
            data-attr={'property-filter-' + index}
            style={{
                maxWidth: '90vw',
            }}
        >
            <Popover
                trigger="click"
                onVisibleChange={handleVisibleChange}
                destroyTooltipOnHide={true}
                defaultVisible={false}
                visible={open}
                placement={popoverPlacement || 'bottomLeft'}
                content={
                    <PropertyFilter
                        key={index}
                        index={index}
                        onComplete={() => setOpen(false)}
                        logic={logic}
                        selectProps={{
                            delayBeforeAutoOpen: 150,
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
                    onClick={() => {
                        remove(index)
                    }}
                    style={{ cursor: 'pointer', float: 'none', marginLeft: 5 }}
                />
            )}
            {key && showConditionBadge && index + 1 < totalCount && (
                <span style={{ marginLeft: 16, right: 16, position: 'absolute' }} className="stateful-badge and">
                    AND
                </span>
            )}
        </Row>
    )
})
