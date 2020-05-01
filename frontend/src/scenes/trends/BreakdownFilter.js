import React, { Component } from 'react'
import { selectStyle } from '../../lib/utils'
import { Select, Row } from 'antd'

export class BreakdownFilter extends Component {
    render() {
        return (
            <Select
                style={{ width: '80%', maxWidth: 200 }}
                placeholder={'Break down by'}
                value={this.props.breakdown ? this.props.breakdown : undefined}
                onChange={value => this.props.onChange(value)}
                styles={selectStyle}
            >
                {Object.entries(this.props.properties).map(([key, item]) => {
                    return (
                        <Select.Option key={key} value={item.value}>
                            {item.label}
                        </Select.Option>
                    )
                })}
            </Select>
        )
    }
}
