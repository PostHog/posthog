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
                >
                    <Select.Option value={'Volume'}>{'Volume'}</Select.Option>
                    <Select.Option value={'Stickiness'}>{'Stickiness'}</Select.Option>
                </Select>
            </Row>

            <Row>
                {shown_as == 'Stickiness' && (
                    <small>
                        <i>
                            Stickiness shows you how many days users performed an action within the timeframe. If a user
                            performed an action on Monday and came back and did it twice on Friday, it would be listed
                            as "2 days" in the chart.
                        </i>
                    </small>
                )}
            </Row>
        </div>
    )
}
