import React, { useState, useEffect } from 'react'
import { Select } from 'antd'
import api from '../../api'
import { isMobile, isOperatorFlag, isOperatorMulti, isOperatorRegex, isValidRegex } from 'lib/utils'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'

export function PropertyValue({
    propertyKey,
    type,
    endpoint,
    placeholder,
    style,
    bordered = true,
    onSet,
    value,
    operator,
    outerOptions,
}) {
    const [input, setInput] = useState('')
    const [optionsCache, setOptionsCache] = useState({})
    const [options, setOptions] = useState({})

    function loadPropertyValues(newInput) {
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
    }

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

    return (
        <>
            <SelectGradientOverflow
                mode={isOperatorMulti(operator) ? 'multiple' : undefined}
                showSearch
                autoFocus={!value && !isMobile()}
                style={{ width: '100%', ...style }}
                onChange={(value, payload) => {
                    if (isOperatorMulti(operator) && payload.length > 0) {
                        setValue(value)
                    } else {
                        setValue(payload?.value ?? null)
                    }
                }}
                value={value || placeholder}
                loading={optionsCache[input] === 'loading'}
                onSearch={(newInput) => {
                    setInput(newInput)
                    if (!optionsCache[newInput] && !isOperatorFlag(operator)) {
                        loadPropertyValues(newInput)
                    }
                }}
                data-attr="prop-val"
                dropdownMatchSelectWidth={350}
                bordered={bordered}
                placeholder={placeholder}
                allowClear={value}
                onKeyDown={(e) => {
                    if (e.key === 'Escape') {
                        e.target.blur()
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
                    >
                        {name === true && 'true'}
                        {name === false && 'false'}
                        {name}
                    </Select.Option>
                ))}
            </SelectGradientOverflow>
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
