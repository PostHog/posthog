import React, { Component } from 'react'
import { selectStyle } from '../../lib/utils'
import { Select } from 'antd'

export class BreakdownFilter extends Component {
    render() {
        return (
            <div style={{ width: 200, display: 'inline-block' }}>
                <Select
                    style={{ width: 200 }}
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
            </div>
        )
    }
}
