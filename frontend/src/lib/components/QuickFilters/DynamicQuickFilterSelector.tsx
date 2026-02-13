import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { PropertyDefinitionType, PropertyFilterType, PropertyOperator } from '~/types'

interface DynamicQuickFilterSelectorProps {
    label: string
    propertyName: string
    regexPattern: string | null
    operator: PropertyOperator
    selectedValue: string | null
    onChange: (value: string | null, operator: PropertyOperator) => void
}

export function DynamicQuickFilterSelector({
    label,
    propertyName,
    regexPattern,
    operator,
    selectedValue,
    onChange,
}: DynamicQuickFilterSelectorProps): JSX.Element {
    const { options: propertyOptions } = useValues(propertyDefinitionsModel)
    const { loadPropertyValues } = useActions(propertyDefinitionsModel)
    const compiledRegex = useRef<RegExp | null>(null)

    useEffect(() => {
        if (regexPattern) {
            try {
                compiledRegex.current = new RegExp(regexPattern)
            } catch {
                compiledRegex.current = null
            }
        } else {
            compiledRegex.current = null
        }
    }, [regexPattern])

    const propertyData = propertyOptions[propertyName]
    const isLoading = propertyData?.status === 'loading'

    const filteredValues = useMemo(() => {
        const values = propertyData?.values || []
        if (!compiledRegex.current) {
            return values
        }
        return values.filter((v: any) => compiledRegex.current!.test(String(v.name ?? '')))
    }, [propertyData?.values, regexPattern]) // eslint-disable-line react-hooks/exhaustive-deps

    const allOptions = useMemo(
        () => [
            { value: null as string | null, label: `Any ${label.toLowerCase()}` },
            ...filteredValues.map((v: any) => {
                const strValue = String(v.name ?? '')
                return { value: strValue, label: strValue }
            }),
            // Keep selected value visible even if not in current results
            ...(selectedValue && !filteredValues.some((v: any) => String(v.name) === selectedValue)
                ? [{ value: selectedValue, label: selectedValue }]
                : []),
        ],
        [filteredValues, label, selectedValue]
    )

    const handleClick = useCallback(() => {
        loadPropertyValues({
            endpoint: undefined,
            type: propertyFilterTypeToPropertyDefinitionType(PropertyFilterType.Event) as PropertyDefinitionType,
            newInput: '',
            propertyKey: propertyName,
            eventNames: [],
            properties: [],
        })
    }, [loadPropertyValues, propertyName])

    return (
        <LemonSelect
            value={selectedValue}
            onChange={(value) => onChange(value, operator)}
            options={allOptions}
            size="small"
            placeholder={label}
            dropdownMatchSelectWidth={false}
            loading={isLoading}
            onClick={handleClick}
        />
    )
}
