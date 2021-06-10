import React, { useState, useEffect } from 'react'
import { AutoComplete, Select } from 'antd'
import { useThrottledCallback } from 'use-debounce'
import api from 'lib/api'
import { isMobile, isOperatorFlag, isOperatorMulti, isOperatorRegex, isValidRegex, toString } from 'lib/utils'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { PropertyOperator } from '~/types'

type PropValue = {
    name?: string | boolean
}

type Option = {
    label?: string
    name?: string
    status?: 'loading' | 'loaded'
    values?: PropValue[]
}

interface PropertyValueProps {
    propertyKey: string
    type: string
    endpoint?: string // Endpoint to fetch options from
    placeholder?: string
    style?: Partial<React.CSSProperties>
    bordered?: boolean
    onSet: CallableFunction
    value?: string | number | Array<string | number> | null
    operator?: PropertyOperator
    outerOptions?: Option[] // If no endpoint provided, options are given here
}

function matchesLowerCase(needle: string, haystack?: string): boolean {
    if (typeof haystack !== 'string') {
        return false
    }
    return haystack.toLowerCase().indexOf(needle.toLowerCase()) > -1
}

function getValidationError(operator: PropertyOperator, value: any): string | null {
    if (isOperatorRegex(operator) && !isValidRegex(value)) {
        return 'Value is not a valid regular expression'
    }
    return null
}

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
}: PropertyValueProps): JSX.Element {
    const isMultiSelect = operator && isOperatorMulti(operator)
    const [input, setInput] = useState(isMultiSelect ? '' : toString(value))
    const [options, setOptions] = useState({} as Record<string, Option>)

    const loadPropertyValues = useThrottledCallback((newInput) => {
        if (type === 'cohort') {
            return
        }
        const key = propertyKey.split('__')[0]
        setOptions({ [propertyKey]: { ...options[propertyKey], status: 'loading' }, ...options })
        if (outerOptions) {
            setOptions({
                [propertyKey]: {
                    values: [...Array.from(new Set(outerOptions))],
                    status: 'loaded',
                },
                ...options,
            })
        } else {
            api.get(endpoint || 'api/' + type + '/values/?key=' + key + (newInput ? '&value=' + newInput : '')).then(
                (propValues: PropValue[]) => {
                    setOptions({
                        [propertyKey]: {
                            values: [...Array.from(new Set(propValues))],
                            status: 'loaded',
                        },
                        ...options,
                    })
                }
            )
        }
    }, 300)

    function setValue(newValue: PropertyValueProps['value']): void {
        onSet(newValue)
        if (isMultiSelect) {
            setInput('')
        }
    }

    useEffect(() => {
        loadPropertyValues('')
    }, [propertyKey])

    const displayOptions = ((options[propertyKey] && options[propertyKey].values) || []).filter(
        (option) => input === '' || matchesLowerCase(input, toString(option?.name))
    )

    const validationError = operator ? getValidationError(operator, value) : null

    const commonInputProps = {
        autoFocus: !value && !isMobile(),
        style: { width: '100%', ...style },
        loading: options[input]?.status === 'loading',
        onSearch: (newInput: string) => {
            setInput(newInput)
            if (!Object.keys(options).includes(newInput) && !(operator && isOperatorFlag(operator))) {
                loadPropertyValues(newInput)
            }
        },
        ['data-attr']: 'prop-val',
        dropdownMatchSelectWidth: 350,
        bordered,
        placeholder,
        allowClear: Boolean(value),
        onKeyDown: (e: React.KeyboardEvent) => {
            if (e.key === 'Escape' && e.target instanceof HTMLElement) {
                e.target.blur()
            }
            if (!isMultiSelect && e.key === 'Enter') {
                setValue(input)
            }
        },
    }

    return (
        <>
            {isMultiSelect ? (
                <SelectGradientOverflow
                    {...commonInputProps}
                    value={value}
                    mode="multiple"
                    showSearch
                    onChange={(val, payload) => {
                        if (Array.isArray(payload) && payload.length > 0) {
                            setValue(val)
                        } else if (payload instanceof Option) {
                            setValue(payload?.value ?? [])
                        } else {
                            setValue([])
                        }
                    }}
                >
                    {input && (
                        <Select.Option key="specify-value" value={input} className="ph-no-capture">
                            Specify: {input}
                        </Select.Option>
                    )}
                    {displayOptions.map(({ name: _name }, index) => {
                        const name = toString(_name)
                        return (
                            <Select.Option
                                key={name}
                                value={name}
                                data-attr={'prop-val-' + index}
                                className="ph-no-capture"
                                title={name}
                            >
                                {name}
                            </Select.Option>
                        )
                    })}
                </SelectGradientOverflow>
            ) : (
                <AutoComplete
                    {...commonInputProps}
                    value={input}
                    onChange={(val) => {
                        setInput(toString(val))
                    }}
                    onSelect={(val) => {
                        setValue(toString(val))
                    }}
                >
                    {input && (
                        <AutoComplete.Option key="specify-value" value={input} className="ph-no-capture">
                            Specify: {input}
                        </AutoComplete.Option>
                    )}
                    {displayOptions.map(({ name: _name }, index) => {
                        const name = toString(_name)
                        return (
                            <AutoComplete.Option
                                key={name}
                                value={name}
                                data-attr={'prop-val-' + index}
                                className="ph-no-capture"
                                title={name}
                            >
                                {name}
                            </AutoComplete.Option>
                        )
                    })}
                </AutoComplete>
            )}
            {validationError && <p className="text-danger">{validationError}</p>}
        </>
    )
}
