import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { DurationPicker } from 'lib/components/DurationPicker/DurationPicker'
import { PropertyFilterDatePicker } from 'lib/components/PropertyFilters/components/PropertyFilterDatePicker'
import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { formatDate, isOperatorDate, isOperatorFlag, isOperatorMulti, toString } from 'lib/utils'
import { useEffect } from 'react'

import {
    PROPERTY_FILTER_TYPES_WITH_ALL_TIME_SUGGESTIONS,
    PROPERTY_FILTER_TYPES_WITH_TEMPORAL_SUGGESTIONS,
    propertyDefinitionsModel,
} from '~/models/propertyDefinitionsModel'
import { PropertyFilterType, PropertyOperator, PropertyType } from '~/types'

export interface PropertyValueProps {
    propertyKey: string
    type: PropertyFilterType
    endpoint?: string // Endpoint to fetch options from
    placeholder?: string
    onSet: CallableFunction
    value?: string | number | Array<string | number> | null
    operator: PropertyOperator
    autoFocus?: boolean
    eventNames?: string[]
    addRelativeDateTimeOptions?: boolean
}

export function PropertyValue({
    propertyKey,
    type,
    endpoint = undefined,
    placeholder = undefined,
    onSet,
    value,
    operator,
    autoFocus = false,
    eventNames = [],
    addRelativeDateTimeOptions = false,
}: PropertyValueProps): JSX.Element {
    const { formatPropertyValueForDisplay, describeProperty, options } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)

    const isMultiSelect = operator && isOperatorMulti(operator)
    const isDateTimeProperty = operator && isOperatorDate(operator)
    const propertyDefinitionType = propertyFilterTypeToPropertyDefinitionType(type)

    const isDurationProperty =
        propertyKey && describeProperty(propertyKey, propertyDefinitionType) === PropertyType.Duration

    const load = (newInput: string | undefined): void => {
        loadPropertyValues({
            endpoint,
            type: propertyDefinitionType,
            newInput,
            propertyKey,
            eventNames,
        })
    }

    const setValue = (newValue: PropertyValueProps['value']): void => onSet(newValue)

    useEffect(() => {
        load('')
    }, [propertyKey])

    const displayOptions = options[propertyKey]?.values || []

    const onSearchTextChange = (newInput: string): void => {
        if (!Object.keys(options).includes(newInput) && !(operator && isOperatorFlag(operator))) {
            load(newInput.trim())
        }
    }

    if (isDurationProperty) {
        return <DurationPicker autoFocus={autoFocus} value={value as number} onChange={setValue} />
    }

    if (isDateTimeProperty) {
        if (!addRelativeDateTimeOptions || operator === PropertyOperator.IsDateExact) {
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

    const formattedValues = (value === null || value === undefined ? [] : Array.isArray(value) ? value : [value]).map(
        (label) => String(formatPropertyValueForDisplay(propertyKey, label))
    )

    return (
        <LemonInputSelect
            data-attr="prop-val"
            loading={options[propertyKey]?.status === 'loading'}
            value={formattedValues}
            mode={isMultiSelect ? 'multiple' : 'single'}
            allowCustomValues={options[propertyKey]?.allowCustomValues ?? true}
            onChange={(nextVal) => (isMultiSelect ? setValue(nextVal) : setValue(nextVal[0]))}
            onInputChange={onSearchTextChange}
            placeholder={placeholder}
            title={
                PROPERTY_FILTER_TYPES_WITH_TEMPORAL_SUGGESTIONS.includes(type)
                    ? 'Suggested values (last 7 days)'
                    : PROPERTY_FILTER_TYPES_WITH_ALL_TIME_SUGGESTIONS.includes(type)
                    ? 'Suggested values'
                    : undefined
            }
            popoverClassName="max-w-200"
            options={displayOptions.map(({ name: _name }, index) => {
                const name = toString(_name)
                return {
                    key: name,
                    label: name,
                    labelComponent: (
                        <span key={name} data-attr={'prop-val-' + index} className="ph-no-capture" title={name}>
                            {name === '' ? <i>(empty string)</i> : formatPropertyValueForDisplay(propertyKey, name)}
                        </span>
                    ),
                }
            })}
        />
    )
}
