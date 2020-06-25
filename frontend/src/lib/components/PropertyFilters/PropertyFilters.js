import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { Popover, Row } from 'antd'
import { CloseButton, operatorMap } from 'lib/utils'
import _ from 'lodash'

function FilterRow({ item, index, filters, logic, pageKey }) {
    const { remove } = useActions(logic)
    let [open, setOpen] = useState(false)
    const { key, value, operator, type } = item

    let handleVisibleChange = visible => {
        if (!visible && Object.keys(item).length >= 0 && !item[Object.keys(item)[0]]) {
            remove(index)
        }
        setOpen(visible)
    }

    return (
        <Row align="middle" className="mt-2 mb-2">
            <Popover
                trigger="click"
                onVisibleChange={handleVisibleChange}
                defaultVisible={false}
                visible={open}
                placement="bottomLeft"
                content={<PropertyFilter key={index} index={index} onComplete={() => setOpen(false)} logic={logic} />}
            >
                {key ? (
                    <Button type="primary" shape="round" style={{ maxWidth: '85%' }}>
                        <span style={{ width: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {keyMapping[type === 'element' ? 'element' : 'event'][key]?.label || key}{' '}
                            {operatorMap[operator || 'exact'].split(' ')[0]} {value}
                        </span>
                    </Button>
                ) : (
                    <Button type="default" shape="round" data-attr={'new-prop-filter-' + pageKey}>
                        {'New Filter'}
                    </Button>
                )}
            </Popover>
            {!_.isEmpty(filters[index]) && (
                <CloseButton
                    className="ml-1"
                    onClick={() => {
                        remove(index)
                    }}
                    style={{ cursor: 'pointer', float: 'none' }}
                />
            )}
        </Row>
    )
}

export function PropertyFilters({ endpoint, propertyFilters, onChange, pageKey }) {
    const logic = propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey })
    const { filters } = useValues(logic)

    return (
        <div className="column" style={{ marginBottom: '15px' }}>
            {filters &&
                filters.map((item, index) => {
                    return (
                        <FilterRow
                            key={index === filters.length - 1 ? index : `${index}_${Object.keys(item)[0]}`}
                            logic={logic}
                            item={item}
                            index={index}
                            filters={filters}
                            pageKey={pageKey}
                        />
                    )
                })}
        </div>
    )
}
