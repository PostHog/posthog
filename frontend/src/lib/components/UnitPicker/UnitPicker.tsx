import './UnitPicker.scss'
import {
    AggregationAxisFormat,
    aggregationAxisFormatSelectOptions,
    axisLabel,
} from 'scenes/insights/aggregationAxisFormat'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { currencies, CurrencyPicker, isCurrency } from 'lib/components/CurrencyPicker/CurrencyPicker'
import React, { useMemo, useState } from 'react'
import { FilterType } from '~/types'
import currencyMap from 'lib/components/CurrencyPicker/currency-map.json'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'

interface UnitPickerProps {
    filters: FilterType
    onChange?: (a: AggregationAxisFormat) => void
}

const aggregationDisplayMap = aggregationAxisFormatSelectOptions.reduce((acc, option) => {
    acc[option.value] = option.label
    return acc
}, {})

const currencyDisplayMap = Object.entries(currencyMap).reduce((acc, currencyMapping) => {
    const [abbreviation, { symbol }] = currencyMapping
    acc[abbreviation] = `${abbreviation} (${symbol})`
    return acc
}, {})

export function UnitPicker({ filters, onChange }: UnitPickerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const [isVisible, setIsVisible] = useState(false)
    const [localValue, setLocalValue] = useState(filters.aggregation_axis_format || 'numeric')

    const handleChange = (value: AggregationAxisFormat): void => {
        setLocalValue(value)
        setIsVisible(false)
        onChange?.(value)
    }

    const display = useMemo(() => {
        if (isCurrency(localValue)) {
            return currencyDisplayMap[localValue]
        }
        return aggregationDisplayMap[localValue]
    }, [localValue])

    return (
        <>
            <span>{axisLabel(filters.display)}</span>
            <LemonButtonWithPopup
                onClick={() => setIsVisible(!isVisible)}
                size={'small'}
                type={'secondary'}
                status="stealth"
                data-attr="chart-aggregation-axis-format"
                popup={{
                    onClickOutside: close,
                    visible: isVisible,
                    className: 'UnitPopup',
                    overlay: (
                        <>
                            {aggregationAxisFormatSelectOptions.map(({ value, label }, index) => (
                                <LemonButton
                                    key={index}
                                    onClick={() => handleChange(value)}
                                    status="stealth"
                                    active={value === localValue}
                                    fullWidth
                                >
                                    {label}
                                </LemonButton>
                            ))}
                            {!!featureFlags[FEATURE_FLAGS.CURRENCY_UNITS] && (
                                <>
                                    <LemonDivider />
                                    <h5>Currency</h5>
                                    <CurrencyPicker
                                        value={
                                            isCurrency(localValue)
                                                ? (localValue as currencies)
                                                : ([] as unknown as currencies)
                                        }
                                        onChange={(currency) => {
                                            handleChange(currency)
                                        }}
                                    />
                                </>
                            )}
                        </>
                    ),
                    placement: 'bottom-start',
                    actionable: true,
                    closeOnClickInside: false,
                }}
            >
                {display}
            </LemonButtonWithPopup>
        </>
    )
}
