import './PropertyValue.scss'

import { AutoComplete } from 'antd'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { PropertyFilterDatePicker } from 'lib/components/PropertyFilters/components/PropertyFilterDatePicker'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { LemonSelectMultiple } from 'lib/lemon-ui/LemonSelectMultiple/LemonSelectMultiple'
import { formatDate, isOperatorDate, isOperatorFlag, isOperatorMulti, toString } from 'lib/utils'
import { useEffect, useRef, useState } from 'react'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

export interface PropertyValueProps {
    propertyKey: string
    type: PropertyFilterType
    endpoint?: string // Endpoint to fetch options from
    placeholder?: string
    className?: string
    onSet: CallableFunction
    value?: string | number | Array<string | number> | null
    operator: PropertyOperator
    autoFocus?: boolean
    allowCustom?: boolean
    eventNames?: string[]
    addRelativeDateTimeOptions?: boolean
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
    onSet,
    value,
    operator,
    autoFocus = false,
    allowCustom = true,
    eventNames = [],
    addRelativeDateTimeOptions = false,
}: PropertyValueProps): JSX.Element {
    // what the human has typed into the box
    const [input, setInput] = useState(Array.isArray(value) ? '' : toString(value) ?? '')

    const [shouldBlur, setShouldBlur] = useState(false)
    const autoCompleteRef = useRef<HTMLElement>(null)

    const { formatPropertyValueForDisplay, describeProperty, options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const isMultiSelect = operator && isOperatorMulti(operator)
    const isDateTimeProperty = operator && isOperatorDate(operator)
    const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(type)

    const isDurationProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Duration

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

    const load = (newInput: string | undefined): void => {
        loadPropertyValues({
            endpoint,
            type: propertyDefinitionType,
            newInput,
            propertyKey,
            eventNames,
        })
    }

    function setValue(newValue: PropertyValueProps['value']): void {
        onSet(newValue)
        if (isMultiSelect) {
            setInput('')
        }
    }

    useEffect(() => {
        load('')
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
                load(newInput.trim())
            }
        },
        ['data-attr']: 'prop-val',
        dropdownMatchSelectWidth: 350,
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
                onChange={(nextVal: string[]) => {
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

    if (isDateTimeProperty && addRelativeDateTimeOptions) {
        if (operator === PropertyOperator.IsDateExact) {
            return (
                <PropertyFilterDatePicker autoFocus={autoFocus} operator={operator} value={value} setValue={setValue} />
            )
        }

        return (
            <DateFilter
                dateFrom={String(value)}
                onChange={setValue}
                max={10000}
                isFixedDateMode
                dateOptions={[
                    {
                        key: 'Last 24 hours',
                        values: ['-24h'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(24, 'h')),
                        defaultInterval: 'hour',
                    },
                    {
                        key: 'Last 7 days',
                        values: ['-7d'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(7, 'd')),
                        defaultInterval: 'day',
                    },
                    {
                        key: 'Last 14 days',
                        values: ['-14d'],
                        getFormattedDate: (date: dayjs.Dayjs): string => formatDate(date.subtract(14, 'd')),
                        defaultInterval: 'day',
                    },
                ]}
                size="medium"
                makeLabel={(_, startOfRange) => (
                    <span className="hide-when-small">
                        Matches all values {operator === PropertyOperator.IsDateBefore ? 'before' : 'after'}{' '}
                        {startOfRange} if evaluated today.
                    </span>
                )}
            />
        )
    }

    return isDateTimeProperty ? (
        <PropertyFilterDatePicker autoFocus={autoFocus} operator={operator} value={value} setValue={setValue} />
    ) : isDurationProperty ? (
        <DurationPicker autoFocus={autoFocus} value={value as number} onChange={setValue} />
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
