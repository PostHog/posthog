import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { Popover, Row } from 'antd'
import { CloseButton } from 'lib/components/CloseButton'
import PropertyFilterButton from './PropertyFilterButton'
import '../../../scenes/actions/Actions.scss'

const FilterRow = React.memo(function FilterRow({
    item,
    index,
    filters,
    logic,
    pageKey,
    showConditionBadge,
    totalCount,
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
        <Row align="middle" className="mt-05 mb-05">
            <Popover
                trigger="click"
                onVisibleChange={handleVisibleChange}
                defaultVisible={false}
                visible={open}
                placement="bottomLeft"
                content={<PropertyFilter key={index} index={index} onComplete={() => setOpen(false)} logic={logic} />}
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
                    style={{ cursor: 'pointer', float: 'none' }}
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

export function PropertyFilters({
    endpoint = null,
    propertyFilters = null,
    onChange = null,
    pageKey,
    showConditionBadge = false,
}) {
    const logic = propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey })
    const { filters } = useValues(logic)

    return (
        <div className="mb">
            {filters &&
                filters.map((item, index) => {
                    return (
                        <FilterRow
                            key={index === filters.length - 1 ? index : `${index}_${Object.keys(item)[0]}`}
                            logic={logic}
                            item={item}
                            index={index}
                            totalCount={filters.length - 1} // empty state
                            filters={filters}
                            pageKey={pageKey}
                            showConditionBadge={showConditionBadge}
                        />
                    )
                })}
        </div>
    )
}
