import React, { Component } from 'react'
import Select from 'react-select'
import { selectStyle } from '../../lib/utils'

export default class BreakdownFilter extends Component {
  render() {
    return <div style={{width: 200, display: 'inline-block'}}>
      <Select
        cacheOptions
        defaultOptions
        style={{width: 200}}
        placeholder={"Break down by"}
        value={this.props.breakdown ? {label: this.props.breakdown, value: this.props.breakdown} : null}
        onChange={(item) => this.props.onChange(item.value)}
        styles={selectStyle}
        options={this.props.properties} />
    </div>
  }
}
