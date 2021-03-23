import React from 'react'
import { Select, Row, Tooltip } from 'antd'
import { ACTIONS_BAR_CHART, ShownAsValue } from 'lib/constants'

export function ShownAsFilter({ filters, onChange }) {
    return (
        <div>
            <Row>
                <Tooltip title={filters.breakdown && 'Shown as is not yet available in combination with breakdown'}>
                    <Select
                        defaultValue={filters.shown_as}
                        value={filters.shown_as || ShownAsValue.VOLUME}
                        onChange={(value) =>
                            onChange({
                                shown_as: value,
                                ...(value === ShownAsValue.LIFECYCLE
                                    ? { display: ACTIONS_BAR_CHART, formula: '' }
                                    : {}),
                            })
                        }
                        style={{ width: 200 }}
                        disabled={filters.breakdown}
                        data-attr="shownas-filter"
                    >
                        <Select.Option data-attr="shownas-volume-option" value={ShownAsValue.VOLUME}>
                            {ShownAsValue.VOLUME}
                        </Select.Option>
                        <Select.Option data-attr="shownas-stickiness-option" value={ShownAsValue.STICKINESS}>
                            {ShownAsValue.STICKINESS}
                        </Select.Option>
                        <Select.Option data-attr="shownas-lifecycle-option" value={ShownAsValue.LIFECYCLE}>
                            {ShownAsValue.LIFECYCLE}
                        </Select.Option>
                    </Select>
                </Tooltip>
            </Row>
        </div>
    )
}
