import React, { Component } from 'react'
import api from '../../api'
import { Select } from 'antd'
import { debounce } from '../../utils'
import PropTypes from 'prop-types'

export class PropertyValue extends Component {
    constructor(props) {
        super(props)
        this.state = {
            input: '',
            optionsCache: [],
            options: [],
        }
        this.loadPropertyValues = debounce(this.loadPropertyValues.bind(this), 250)
        this.loadPropertyValues('')
    }
    loadPropertyValues(value) {
        let key = this.props.propertyKey.split('__')[0]
        this.setState({ optionsCache: { ...this.state.optionsCache, [value]: true } })
        api.get('api/' + this.props.endpoint + '/values/?key=' + key + (value ? '&value=' + value : '')).then(
            propValues =>
                this.setState({
                    options: [...new Set([...this.state.options, ...propValues.map(option => option.name)])],
                })
        )
    }
    render() {
        let { onSet, value } = this.props
        let { input, optionsCache, options } = this.state
        options = options.filter(option => input === '' || option.toLowerCase().indexOf(input.toLowerCase()) > -1)
        return (
            <Select
                showSearch
                autoFocus={!value}
                style={{ width: '100%' }}
                onChange={(_, { value }) => onSet(value)}
                onSearch={input => {
                    this.setState({ input })
                    if (!optionsCache[input]) this.loadPropertyValues(input)
                }}
            >
                {input && (
                    <Select.Option key={input} value={input}>
                        Specify: {input}
                    </Select.Option>
                )}
                {options.map(option => (
                    <Select.Option key={option} value={option}>
                        {option}
                    </Select.Option>
                ))}
            </Select>
        )
    }
}
PropertyValue.propTypes = {
    propertyKey: PropTypes.string.isRequired,
    value: PropTypes.any.isRequired,
    onSet: PropTypes.func.isRequired,
}
