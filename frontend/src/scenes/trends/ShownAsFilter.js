import React from 'react'
import { Select, Row } from 'antd'

export function ShownAsFilter({ shown_as, onChange }) {
    return (
        <div>
            <Row>
                <Select
                    defaultValue={shown_as}
                    value={shown_as || 'Volume'}
                    onChange={value => onChange(value)}
                    style={{ width: 200 }}
                    dataattr="shownas-filter"
                >
                    <Select.Option dataattr="shownas-volume-option" value={'Volume'}>
                        {'Volume'}
                    </Select.Option>
                    <Select.Option dataattr="shownas-stickiness-option" value={'Stickiness'}>
                        {'Stickiness'}
                    </Select.Option>
                </Select>
            </Row>
        </div>
    )
}
