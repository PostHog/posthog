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
            options: props.operator === 'is_set' ? ['true', 'false'] : [],
        }

        this.loadPropertyValues = debounce(this.loadPropertyValues.bind(this), 250)
        if (this.props.operator !== 'is_set') {
            this.loadPropertyValues('')
        }
    }
    loadPropertyValues(input) {
        let key = this.props.propertyKey.split('__')[0]

        this.setState({ input, optionsCache: { ...this.state.optionsCache, [input]: 'loading' } })
        api.get('api/' + this.props.endpoint + '/values/?key=' + key + (input ? '&value=' + input : '')).then(
            propValues =>
                this.setState({
                    options: [...new Set([...this.state.options, ...propValues.map(option => option.name)])],
                    optionsCache: { ...this.state.optionsCache, [input]: true },
                })
        )
    }
    render() {
        let { onSet, value, operator } = this.props
        let { input, optionsCache, options } = this.state
        options = options.filter(option => input === '' || option.toLowerCase().indexOf(input.toLowerCase()) > -1)
        return (
            <Select
                showSearch
                autoFocus={!value}
                style={{ width: '100%' }}
                onChange={(_, { value }) => onSet(value)}
                value={value}
                loading={optionsCache[input] === 'loading'}
                onSearch={input => {
                    if (!optionsCache[input] && operator !== 'is_set') this.loadPropertyValues(input)
                }}
            >
                {input && (
                    <Select.Option key={input} value={input}>
                        Specify: {input}
                    </Select.Option>
                )}
                {options.map(option => (
                    <Select.Option key={option} value={option}>
                        {option === true && 'true'}
                        {option === false && 'false'}
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
