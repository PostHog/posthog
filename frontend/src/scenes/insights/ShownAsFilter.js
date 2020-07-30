import React from 'react'
import { Select, Row, Tooltip } from 'antd'

export function ShownAsFilter({ filters, onChange }) {
    return (
        <div>
            <Row>
                <Tooltip title={filters.breakdown && 'Shown as is not yet available in combination with breakdown'}>
                    <Select
                        defaultValue={filters.shown_as}
                        value={filters.shown_as || 'Volume'}
                        onChange={(value) => onChange(value)}
                        style={{ width: 200 }}
                        disabled={filters.breakdown}
                        data-attr="shownas-filter"
                    >
                        <Select.Option data-attr="shownas-volume-option" value={'Volume'}>
                            {'Volume'}
                        </Select.Option>
                        <Select.Option data-attr="shownas-stickiness-option" value={'Stickiness'}>
                            {'Stickiness'}
                        </Select.Option>
                    </Select>
                </Tooltip>
            </Row>
        </div>
    )
}
