import React, { Component } from 'react'
// import Select from 'react-select'
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
                    options={this.props.properties}
                >
                    {Object.entries(this.props.properties).map(([key, value]) => {
                        return (
                            <Select.Option key={key} value={key}>
                                {value}
                            </Select.Option>
                        )
                    })}
                </Select>
            </div>
        )
    }
}
