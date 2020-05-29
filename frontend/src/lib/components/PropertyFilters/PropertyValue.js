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
        this.loadPropertyValues('', props.propertyKey)
    }

    componentWillReceiveProps(nextProps) {
        if (this.props.propertyKey != nextProps.propertyKey) {
            this.setState({ optionsCache: [], options: [] }, () => this.loadPropertyValues('', nextProps.propertyKey))
        }
    }

    loadPropertyValues(value, propertyKey) {
        let key = propertyKey.split('__')[0]

        this.setState({ input: value, optionsCache: { ...this.state.optionsCache, [value]: 'loading' } })
        api.get('api/' + this.props.type + '/values/?key=' + key + (value ? '&value=' + value : '')).then(
            propValues => {
                this.setState({
                    options: [...new Set([...this.state.options, ...propValues.map(option => option.name)])],
                    optionsCache: { ...this.state.optionsCache, [value]: true },
                })
            }
        )
    }
    render() {
        let { onSet, value, operator } = this.props
        let { input, optionsCache, options } = this.state
        if (operator === 'is_set') options = ['true', 'false']
        options = options.filter(
            option => input === '' || (option && option.toLowerCase().indexOf(input.toLowerCase()) > -1)
        )
        return (
            <Select
                showSearch
                autoFocus={!value}
                style={{ width: '100%', ...this.props.style }}
                onChange={(_, payload) => onSet((payload && payload.value) || null)}
                value={value || this.props.placeholder}
                loading={optionsCache[input] === 'loading'}
                onSearch={input => {
                    if (!optionsCache[input] && operator !== 'is_set') this.loadPropertyValues(input)
                }}
                data-attr="prop-val"
                dropdownMatchSelectWidth={350}
                bordered={this.props.bordered}
                placeholder={this.props.placeholder}
                allowClear={value}
            >
                {input && (
                    <Select.Option key={input} value={input}>
                        Specify: {input}
                    </Select.Option>
                )}
                {options.map((option, index) => (
                    <Select.Option key={option} value={option} data-attr={'prop-val-' + index}>
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
    value: PropTypes.any,
    onSet: PropTypes.func.isRequired,
}
