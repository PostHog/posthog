import React, { useState } from 'react'
import { PropertyFilter, operatorMap } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { Popover, Row } from 'antd'
import { CloseButton } from '../../utils'

const operatorEntries = Object.entries(operatorMap).reverse()

const formatFilterName = str => {
    for (let [key, value] of operatorEntries) {
        if (str.includes(key)) return str.replace('__' + key, '') + ` ${value} `
    }
    return str + ` ${operatorMap['null']} `
}

function FilterRow({ endpoint, propertyFilters, item, index, onChange, pageKey, filters }) {
    const { remove } = useActions(propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey }))
    let [open, setOpen] = useState(false)

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
                        onChange={onChange}
                        onComplete={() => setOpen(false)}
                        pageKey={pageKey}
                    />
                }
            >
                {Object.keys(item).length !== 0 ? (
                    <Button type="primary" shape="round">
                        <span>{formatFilterName(Object.keys(item)[0]) + item[Object.keys(item)[0]]}</span>
                    </Button>
                ) : (
                    <Button type="default" shape="round">
                        {'Add Filter'}
                    </Button>
                )}
            </Popover>
            {index != filters.length - 1 && (
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

export function PropertyFilters(props) {
    let { endpoint, propertyFilters, className, style, onChange, pageKey } = props
    const { filters } = useValues(propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey }))

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
                            <FilterRow key={index} {...props} item={item} index={index} filters={filters}></FilterRow>
                        )
                    })}
            </div>
        </div>
    )
}
