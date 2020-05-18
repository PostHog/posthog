import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { Popover, Row } from 'antd'
import { CloseButton, operatorMap } from 'lib/utils'

function FilterRow({ endpoint, item, index, filters, logic, pageKey }) {
    const { remove } = useActions(logic)
    let [open, setOpen] = useState(false)
    const { key, value, operator } = item

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
                content={
                    <PropertyFilter
                        key={index}
                        index={index}
                        endpoint={endpoint || 'event'}
                        onComplete={() => setOpen(false)}
                        logic={logic}
                    />
                }
            >
                {key ? (
                    <Button type="primary" shape="round" style={{ maxWidth: '85%' }}>
                        <span style={{ width: '100%', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {key} {operatorMap[operator || 'exact'].split(' ')[0]} {value}
                        </span>
                    </Button>
                ) : (
                    <Button type="default" shape="round" dataattr={'new-prop-filter-' + pageKey}>
                        {'New Filter'}
                    </Button>
                )}
            </Popover>
            {index !== filters.length - 1 && (
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

export function PropertyFilters({ endpoint, propertyFilters, className, style, onChange, pageKey }) {
    const logic = propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey })
    const { filters } = useValues(logic)

    return (
        <div
            className={className || 'col-8'}
            style={{
                padding: 0,
                marginBottom: '2rem',
                display: 'inline',
                style,
            }}
        >
            <div className="column">
                {filters &&
                    filters.map((item, index) => {
                        return (
                            <FilterRow
                                key={index === filters.length - 1 ? index : `${index}_${Object.keys(item)[0]}`}
                                logic={logic}
                                item={item}
                                index={index}
                                filters={filters}
                                endpoint={endpoint}
                                pageKey={pageKey}
                            />
                        )
                    })}
            </div>
        </div>
    )
}
