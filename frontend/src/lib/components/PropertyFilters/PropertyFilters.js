import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { Popover, Row } from 'antd'
import { CloseButton } from '../../utils'
import { CloseOutlined } from '@ant-design/icons'

const formatFilterName = str => {
    if (str.includes('__is_not')) return str.replace('__is_not', '') + ' is not '
    else if (str.includes('__icontains')) return str.replace('__icontains', '') + ' contains '
    else if (str.includes('__not_icontains')) return str.replace('__not_icontains', '') + ' does not contain '
    else if (str.includes('__gt')) return str.replace('__gt', '') + ' > '
    else if (str.includes('__lt')) return str.replace('__lt', '') + ' < '
    else return str.replace('__null', '') + ' = '
}

function FilterRow({ endpoint, propertyFilters, item, index, onChange, pageKey, filters }) {
    const { remove } = useActions(propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey }))
    let [open, setOpen] = useState(false)

    let handleVisibleChange = visible => setOpen(visible)

    return (
        <Row align="middle">
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
                    <Button type="primary" shape="round" style={{ marginTop: '0.5rem' }}>
                        <span>{formatFilterName(Object.keys(item)[0]) + item[Object.keys(item)[0]]}</span>
                    </Button>
                ) : (
                    <Button type="default" shape="round" style={{ marginTop: '0.5rem', marginBottom: '0.5rem' }}>
                        {filters.length == 0 ? 'Filter by property' : 'Add another filter'}
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
                marginBottom: '2rem',
                padding: 0,
                display: 'inline',
                style,
            }}
        >
            <div className="column">
                {filters &&
                    filters.map((item, index) => {
                        return <FilterRow {...props} item={item} index={index} filters={filters}></FilterRow>
                    })}
            </div>
        </div>
    )
}
