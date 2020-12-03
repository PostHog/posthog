import React from 'react'
import { Select, Row, Tooltip } from 'antd'
import { ACTIONS_BAR_CHART, LIFECYCLE, STICKINESS, VOLUME } from 'lib/constants'

export function ShownAsFilter({ filters, onChange }) {
    return (
        <div>
            <Row>
                <Tooltip title={filters.breakdown && 'Shown as is not yet available in combination with breakdown'}>
                    <Select
                        defaultValue={filters.shown_as}
                        value={filters.shown_as || VOLUME}
                        onChange={(value) =>
                            onChange({
                                shown_as: value,
                                ...(value === LIFECYCLE ? { display: ACTIONS_BAR_CHART } : {}),
                            })
                        }
                        style={{ width: 200 }}
                        disabled={filters.breakdown}
                        data-attr="shownas-filter"
                    >
                        <Select.Option data-attr="shownas-volume-option" value={VOLUME}>
                            {VOLUME}
                        </Select.Option>
                        <Select.Option data-attr="shownas-stickiness-option" value={STICKINESS}>
                            {STICKINESS}
                        </Select.Option>
                        <Select.Option data-attr="shownas-lifecycle-option" value={LIFECYCLE}>
                            {LIFECYCLE}
                        </Select.Option>
                    </Select>
                </Tooltip>
            </Row>
        </div>
    )
}
