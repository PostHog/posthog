import React, { useState, useEffect } from 'react'
import { AutoComplete, Select } from 'antd'
import { useThrottledCallback } from 'use-debounce'
import api from 'lib/api'
import { isMobile, isOperatorFlag, isOperatorMulti, isOperatorRegex, isValidRegex } from 'lib/utils'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'

export function PropertyValue({
    propertyKey,
    type,
    endpoint = undefined,
    placeholder = undefined,
    style = {},
    bordered = true,
    onSet,
    value,
    operator,
    outerOptions = undefined,
}) {
    const [input, setInput] = useState('')
    const [optionsCache, setOptionsCache] = useState({})
    const [options, setOptions] = useState({})

    const loadPropertyValues = useThrottledCallback((newInput) => {
        if (type === 'cohort') {
            return
        }
        let key = propertyKey.split('__')[0]
        setOptions({ [propertyKey]: { ...options[propertyKey], status: 'loading' }, ...options })
        setOptionsCache({ ...optionsCache, [newInput]: 'loading' })
        if (outerOptions) {
            setOptions({
                [propertyKey]: { values: [...new Set([...outerOptions.map((option) => option)])], status: true },
                ...options,
            })
            setOptionsCache({ ...optionsCache, [newInput]: true })
        } else {
            api.get(endpoint || 'api/' + type + '/values/?key=' + key + (newInput ? '&value=' + newInput : '')).then(
                (propValues) => {
                    setOptions({
                        [propertyKey]: { values: [...new Set([...propValues.map((option) => option)])], status: true },
                        ...options,
                    })
                    setOptionsCache({ ...optionsCache, [newInput]: true })
                }
            )
        }
    }, 300)

    function setValue(newValue) {
        onSet(newValue)
        setInput('')
    }

    useEffect(() => {
        loadPropertyValues('')
    }, [propertyKey])

    let displayOptions
    displayOptions = ((options[propertyKey] && options[propertyKey].values) || []).filter(
        (option) => input === '' || (option && option.name?.toLowerCase().indexOf(input.toLowerCase()) > -1)
    )

    const validationError = getValidationError(operator, value)

    const commonInputProps = {
        autoFocus: !value && !isMobile(),
        style: { width: '100%', ...style },
        value: value || placeholder,
        loading: optionsCache[input] === 'loading',
        onSearch: (newInput) => {
            setInput(newInput)
            if (!optionsCache[newInput] && !isOperatorFlag(operator)) {
                loadPropertyValues(newInput)
            }
        },
        ['data-attr']: 'prop-val',
        dropdownMatchSelectWidth: 350,
        bordered,
        placeholder,
        allowClear: value,
        onKeyDown: (e) => {
            if (e.key === 'Escape') {
                e.target.blur()
            }
        },
    }

    return (
        <>
            {isOperatorRegex(operator) ? (
                <AutoComplete
                    {...commonInputProps}
                    onChange={(val) => {
                        setValue(val ?? null)
                    }}
                >
                    {input && (
                        <Select.Option key={input} value={input} className="ph-no-capture">
                            Specify: {input}
                        </Select.Option>
                    )}
                    {displayOptions.map(({ name, id }, index) => (
                        <AutoComplete.Option
                            key={id || name}
                            value={id || name}
                            data-attr={'prop-val-' + index}
                            className="ph-no-capture"
                            title={name}
                        >
                            {name === true && 'true'}
                            {name === false && 'false'}
                            {name}
                        </AutoComplete.Option>
                    ))}
                </AutoComplete>
            ) : (
                <SelectGradientOverflow
                    {...commonInputProps}
                    mode={isOperatorMulti(operator) ? 'multiple' : undefined}
                    showSearch
                    onChange={(val, payload) => {
                        if (isOperatorMulti(operator) && payload.length > 0) {
                            setValue(val)
                        } else {
                            setValue(payload?.value ?? null)
                        }
                    }}
                >
                    {input && (
                        <Select.Option key={input} value={input} className="ph-no-capture">
                            Specify: {input}
                        </Select.Option>
                    )}
                    {displayOptions.map(({ name, id }, index) => (
                        <Select.Option
                            key={id || name}
                            value={id || name}
                            data-attr={'prop-val-' + index}
                            className="ph-no-capture"
                            title={name}
                        >
                            {name === true && 'true'}
                            {name === false && 'false'}
                            {name}
                        </Select.Option>
                    ))}
                </SelectGradientOverflow>
            )}
            {validationError && <p className="text-danger">{validationError}</p>}
        </>
    )
}

function getValidationError(operator, value) {
    if (isOperatorRegex(operator) && !isValidRegex(value)) {
        return 'Value is not a valid regular expression'
    }

    return null
}
