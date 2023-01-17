import { useEffect, useRef, useState } from 'react'
import { AutoComplete } from 'antd'
import { useThrottledCallback } from 'use-debounce'
import api from 'lib/api'
import { isOperatorDate, isOperatorFlag, isOperatorMulti, toString } from 'lib/utils'
import { PropertyOperator, PropertyType } from '~/types'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { useValues } from 'kea'
import { PropertyFilterDatePicker } from 'lib/components/PropertyFilters/components/PropertyFilterDatePicker'
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import './PropertyValue.scss'
import { LemonSelectMultiple } from 'lib/components/LemonSelectMultiple/LemonSelectMultiple'
import clsx from 'clsx'

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

export interface PropertyValueProps {
    propertyKey: string
    type: string
    endpoint?: string // Endpoint to fetch options from
    placeholder?: string
    className?: string
    bordered?: boolean
    onSet: CallableFunction
    value?: string | number | Array<string | number> | null
    operator: PropertyOperator
    autoFocus?: boolean
    allowCustom?: boolean
}

function matchesLowerCase(needle?: string, haystack?: string): boolean {
    if (typeof haystack !== 'string' || typeof needle !== 'string') {
        return false
    }
    return haystack.toLowerCase().indexOf(needle.toLowerCase()) > -1
}

export function PropertyValue({
    propertyKey,
    type,
    endpoint = undefined,
    placeholder = undefined,
    className,
    bordered = true,
    onSet,
    value,
    operator,
    autoFocus = false,
    allowCustom = true,
}: PropertyValueProps): JSX.Element {
    // what the human has typed into the box
    const [input, setInput] = useState(Array.isArray(value) ? '' : toString(value) ?? '')
    // options from the server for search
    const [options, setOptions] = useState({} as Record<string, Option>)

    const [shouldBlur, setShouldBlur] = useState(false)
    const autoCompleteRef = useRef<HTMLElement>(null)

    const { formatPropertyValueForDisplay, describeProperty } = useValues(propertyDefinitionsModel)

    const isMultiSelect = operator && isOperatorMulti(operator)
    const isDateTimeProperty = operator && isOperatorDate(operator)
    const isDurationProperty = propertyKey && describeProperty(propertyKey) === PropertyType.Duration

    // update the input field if passed a new `value` prop
    useEffect(() => {
        if (value == null) {
            setInput('')
        } else if (!Array.isArray(value) && toString(value) !== input) {
            const valueObject = options[propertyKey]?.values?.find((v) => v.id === value)
            if (valueObject) {
                setInput(toString(valueObject.name))
            } else {
                setInput(toString(value))
            }
        }
    }, [value])

    const loadPropertyValues = useThrottledCallback((newInput) => {
        if (['cohort', 'session'].includes(type)) {
            return
        }
        if (!propertyKey) {
            return
        }
        const key = propertyKey.split('__')[0]
        setOptions({ ...options, [propertyKey]: { ...options[propertyKey], status: 'loading' } })
        api.get(endpoint || 'api/' + type + '/values/?key=' + key + (newInput ? '&value=' + newInput : '')).then(
            (propValues: PropValue[]) => {
                setOptions({
                    ...options,
                    [propertyKey]: {
                        values: [...Array.from(new Set(propValues))],
                        status: 'loaded',
                    },
                })
            }
        )
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

    const commonInputProps = {
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

    if (isMultiSelect) {
        const formattedValues = (
            value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]
        ).map((label) => String(formatPropertyValueForDisplay(propertyKey, label)))
        return (
            <LemonSelectMultiple
                loading={options[propertyKey]?.status === 'loading'}
                {...commonInputProps}
                selectClassName={clsx(className, 'property-filters-property-value', 'w-full')}
                value={formattedValues}
                mode="multiple-custom"
                onChange={(nextVal) => {
                    setValue(nextVal)
                }}
                onBlur={commonInputProps.handleBlur}
                // TODO: When LemonSelectMultiple is free of AntD, add footnote that pressing comma applies the value
                options={Object.fromEntries([
                    ...displayOptions.map(({ name: _name }, index) => {
                        const name = toString(_name)
                        return [
                            name,
                            {
                                label: name,
                                labelComponent: (
                                    <span
                                        key={name}
                                        data-attr={'prop-val-' + index}
                                        className="ph-no-capture"
                                        title={name}
                                    >
                                        {name === '' ? (
                                            <i>(empty string)</i>
                                        ) : (
                                            formatPropertyValueForDisplay(propertyKey, name)
                                        )}
                                    </span>
                                ),
                            },
                        ]
                    }),
                ])}
            />
        )
    }

    return isDateTimeProperty ? (
        <PropertyFilterDatePicker autoFocus={autoFocus} operator={operator} value={value} setValue={setValue} />
    ) : isDurationProperty ? (
        <DurationPicker autoFocus={autoFocus} initialValue={value as number} onChange={setValue} />
    ) : (
        <AutoComplete
            {...commonInputProps}
            autoFocus={autoFocus}
            value={input}
            className="h-10 w-full property-filters-property-value"
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
            onKeyDown={(e) => {
                if (e.key === 'Enter') {
                    setInput(toString(input))
                    setValue(toString(input))
                }
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
    )
}
