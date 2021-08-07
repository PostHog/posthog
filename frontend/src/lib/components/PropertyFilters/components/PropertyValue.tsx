import React, { useState, useEffect, useRef } from 'react'
import { AutoComplete, Select } from 'antd'
import { useThrottledCallback } from 'use-debounce'
import api from 'lib/api'
import { isOperatorFlag, isOperatorMulti, isOperatorRegex, toString } from 'lib/utils'
import { SelectGradientOverflow } from 'lib/components/SelectGradientOverflow'
import { PropertyOperator } from '~/types'

type PropValue = {
    id?: number
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
    autoFocus?: boolean
    allowCustom?: boolean
}

function matchesLowerCase(needle?: string, haystack?: string): boolean {
    if (typeof haystack !== 'string' || typeof needle !== 'string') {
        return false
    }
    return haystack.toLowerCase().indexOf(needle.toLowerCase()) > -1
}

function getValidationError(operator: PropertyOperator, value: any): string | null {
    if (isOperatorRegex(operator)) {
        try {
            new RegExp(value)
        } catch (e) {
            return e.message
        }
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
    autoFocus = false,
    allowCustom = true,
}: PropertyValueProps): JSX.Element {
    const isMultiSelect = operator && isOperatorMulti(operator)
    const [input, setInput] = useState(isMultiSelect ? '' : toString(value))
    const [shouldBlur, setShouldBlur] = useState(false)
    const [options, setOptions] = useState({} as Record<string, Option>)
    const autoCompleteRef = useRef<HTMLElement>(null)

    // update the input field if passed a new `value` prop
    useEffect(() => {
        if (!value) {
            setInput('')
        } else if (value !== input) {
            const valueObject = options[propertyKey]?.values?.find((v) => v.id === value)
            if (valueObject) {
                setInput(toString(valueObject.name))
            }
        }
    }, [value])

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

    useEffect(() => {
        if (input === '' && shouldBlur) {
            ;(document.activeElement as HTMLElement)?.blur()
            setShouldBlur(false)
        }
    }, [input, shouldBlur])

    const displayOptions = (options[propertyKey]?.values || []).filter(
        (option) => input === '' || matchesLowerCase(input, toString(option?.name))
    )

    const validationError = operator ? getValidationError(operator, value) : null

    const commonInputProps = {
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
            if (e.key === 'Escape') {
                setInput('')
                setShouldBlur(true)
                return
            }
            if (!isMultiSelect && e.key === 'Enter') {
                // We have not explicitly selected a dropdown item by pressing the up/down keys; or the ref is unavailable
                if (
                    !autoCompleteRef.current ||
                    autoCompleteRef.current?.querySelectorAll?.('.ant-select-item-option-active')?.length === 0
                ) {
                    setValue(input)
                }
            }
        },
        handleBlur: () => {
            if (input != '') {
                if (Array.isArray(value) && !value.includes(input)) {
                    setValue([...value, ...[input]])
                } else if (!Array.isArray(value)) {
                    setValue(input)
                }
                setInput('')
            }
        },
    }

    return (
        <>
            {isMultiSelect ? (
                <SelectGradientOverflow
                    {...commonInputProps}
                    autoFocus={autoFocus}
                    value={value === null ? [] : value}
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
                    {input && !displayOptions.some(({ name }) => input === toString(name)) && (
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
                                {name === '' ? <i>(empty string)</i> : name}
                            </Select.Option>
                        )
                    })}
                </SelectGradientOverflow>
            ) : (
                <AutoComplete
                    {...commonInputProps}
                    autoFocus={autoFocus}
                    value={input}
                    onClear={() => {
                        setInput('')
                        setValue('')
                    }}
                    onChange={(val) => {
                        setInput(toString(val))
                    }}
                    onSelect={(val, option) => {
                        setInput(option.title)
                        setValue(toString(val))
                    }}
                    ref={autoCompleteRef}
                >
                    {[
                        ...(input && allowCustom && !displayOptions.some(({ name }) => input === toString(name))
                            ? [
                                  <AutoComplete.Option key="@@@specify-value" value={input} className="ph-no-capture">
                                      Specify: {input}
                                  </AutoComplete.Option>,
                              ]
                            : []),
                        ...displayOptions.map(({ name: _name, id }, index) => {
                            const name = toString(_name)
                            return (
                                <AutoComplete.Option
                                    key={id ? toString(id) : name}
                                    value={id ? toString(id) : name}
                                    data-attr={'prop-val-' + index}
                                    className="ph-no-capture"
                                    title={name}
                                >
                                    {name}
                                </AutoComplete.Option>
                            )
                        }),
                    ]}
                </AutoComplete>
            )}
            {validationError && <p className="text-danger">{validationError}</p>}
        </>
    )
}
