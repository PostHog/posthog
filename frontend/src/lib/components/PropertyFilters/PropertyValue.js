import React, { useState, useEffect } from 'react'
import api from '../../api'
import { Select } from 'antd'

export function PropertyValue({
    propertyKey,
    type,
    endpoint,
    placeholder,
    style,
    bordered,
    onSet,
    value,
    operator,
    outerOptions,
}) {
    const [input, setInput] = useState('')
    const [optionsCache, setOptionsCache] = useState([])
    const [options, setOptions] = useState([])

    function loadPropertyValues(value) {
        setOptions([])
        let key = propertyKey.split('__')[0]
        setInput(value)
        setOptionsCache({ ...optionsCache, [value]: 'loading' })
        if (outerOptions) {
            setOptions([...new Set([...outerOptions.map(option => option)])])
            setOptionsCache({ ...optionsCache, [value]: true })
        } else {
            api.get(endpoint || 'api/' + type + '/values/?key=' + key + (value ? '&value=' + value : '')).then(
                propValues => {
                    setOptions([...new Set([...propValues.map(option => option)])])
                    setOptionsCache({ ...optionsCache, [value]: true })
                }
            )
        }
    }

    useEffect(() => {
        loadPropertyValues('')
    }, [propertyKey])

    let displayOptions
    if (operator === 'is_set') displayOptions = ['true', 'false']
    displayOptions = options.filter(
        option => input === '' || (option && option.name?.toLowerCase().indexOf(input.toLowerCase()) > -1)
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
            {displayOptions.map(({ name, id }, index) => (
                <Select.Option key={id || name} value={id || name} data-attr={'prop-val-' + index}>
                    {name === true && 'true'}
                    {name === false && 'false'}
                    {name}
                </Select.Option>
            ))}
        </Select>
    )
}
