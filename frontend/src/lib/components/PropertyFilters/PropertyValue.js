import React, { useState, useEffect } from 'react'
import api from '../../api'
import { Select } from 'antd'

export function PropertyValue({ propertyKey, type, placeholder, style, bordered, onSet, value, operator }) {
    const [input, setInput] = useState('')
    const [optionsCache, setOptionsCache] = useState([])
    const [options, setOptions] = useState([])

    function loadPropertyValues(value) {
        let key = propertyKey.split('__')[0]
        setInput(value)
        setOptionsCache({ ...optionsCache, [value]: 'loading' })
        api.get('api/' + type + '/values/?key=' + key + (value ? '&value=' + value : '')).then(propValues => {
            setOptions([...new Set([...options, ...propValues.map(option => option.name)])])
            setOptionsCache({ ...optionsCache, [value]: true })
        })
    }

    useEffect(() => {
        loadPropertyValues('')
    }, [propertyKey])

    let displayOptions
    if (operator === 'is_set') displayOptions = ['true', 'false']
    displayOptions = options.filter(
        option => input === '' || (option && option.toLowerCase().indexOf(input.toLowerCase()) > -1)
    )

    return (
        <Select
            showSearch
            autoFocus={!value}
            style={{ width: '100%', ...style }}
            onChange={(_, payload) => onSet((payload && payload.value) || null)}
            value={value || placeholder}
            loading={optionsCache[input] === 'loading'}
            onSearch={input => {
                if (!optionsCache[input] && operator !== 'is_set') loadPropertyValues(input)
            }}
            data-attr="prop-val"
            dropdownMatchSelectWidth={350}
            bordered={bordered}
            placeholder={placeholder}
            allowClear={value}
        >
            {input && (
                <Select.Option key={input} value={input}>
                    Specify: {input}
                </Select.Option>
            )}
            {displayOptions.map((option, index) => (
                <Select.Option key={option} value={option} data-attr={'prop-val-' + index}>
                    {option === true && 'true'}
                    {option === false && 'false'}
                    {option}
                </Select.Option>
            ))}
        </Select>
    )
}
