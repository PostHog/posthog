import React, { useState } from 'react'
import { PropertyFilter } from './PropertyFilter'
import { Button } from 'antd'
import { useValues, useActions } from 'kea'
import { propertyFilterLogic } from './propertyFilterLogic'
import { cohortsModel } from '../../../models/cohortsModel'
import { keyMapping } from 'lib/components/PropertyKeyInfo'
import { Popover, Row } from 'antd'
import { CloseButton, formatPropertyLabel } from 'lib/utils'
import _ from 'lodash'

const FilterRow = React.memo(function FilterRow({ item, index, filters, cohorts, logic, pageKey }) {
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
                            {formatPropertyLabel(item, cohorts, keyMapping)}
                        </span>
                    </Button>
                ) : (
                    <Button type="default" shape="round" data-attr={'new-prop-filter-' + pageKey}>
                        Add filter
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
})

export function PropertyFilters({ endpoint = null, propertyFilters = null, onChange = null, pageKey }) {
    const logic = propertyFilterLogic({ propertyFilters, endpoint, onChange, pageKey })
    const { filters } = useValues(logic)
    const { cohorts } = useValues(cohortsModel)

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
                            cohorts={cohorts}
                            pageKey={pageKey}
                        />
                    )
                })}
        </div>
    )
}
