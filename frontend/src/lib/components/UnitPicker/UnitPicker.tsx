import './UnitPicker.scss'
import {
    AggregationAxisFormat,
    aggregationAxisFormatSelectOptions,
    axisLabel,
} from 'scenes/insights/aggregationAxisFormat'
import { LemonButton, LemonButtonWithPopup } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import React, { useMemo, useState } from 'react'
import { FilterType, ItemMode } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { PureField } from 'lib/forms/Field'
import { LemonInput } from 'lib/components/LemonInput/LemonInput'
import { useDebouncedCallback } from 'use-debounce'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'

interface UnitPickerProps {
    filters: FilterType
    setFilters: (filters: Partial<FilterType>, insightMode?: ItemMode | undefined) => void
}

const aggregationDisplayMap = aggregationAxisFormatSelectOptions.reduce((acc, option) => {
    acc[option.value] = option.label
    return acc
}, {})

export function UnitPicker({ filters, setFilters }: UnitPickerProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    const [isVisible, setIsVisible] = useState(false)
    const [localAxisFormat, setLocalAxisFormat] = useState(filters.aggregation_axis_format || undefined)
    const [localAxisPrefix, setLocalAxisPrefix] = useState(filters.aggregation_axis_prefix || '')
    const [localAxisPostfix, setLocalAxisPostfix] = useState(filters.aggregation_axis_postfix || '')

    const debouncedVisibilityChange = useDebouncedCallback(() => {
        setIsVisible(!isVisible)
    }, 200)

    const debouncedFilterChange = useDebouncedCallback(
        ({ format, prefix, postfix }: { format?: AggregationAxisFormat; prefix?: string; postfix?: string }) => {
            setFilters({
                ...filters,
                aggregation_axis_format: format,
                aggregation_axis_prefix: prefix,
                aggregation_axis_postfix: postfix,
            })
        },
        200
    )

    useKeyboardHotkeys(
        {
            escape: {
                action: debouncedVisibilityChange,
            },
        },
        []
    )

    const handleChange = ({
        format,
        prefix,
        postfix,
        close,
    }: {
        format?: AggregationAxisFormat
        prefix?: string
        postfix?: string
        close?: boolean
    }): void => {
        setLocalAxisFormat(format)
        setLocalAxisPrefix(prefix || '')
        setLocalAxisPostfix(postfix || '')
        debouncedFilterChange({ format, prefix, postfix })
        if (close) {
            debouncedVisibilityChange()
        }
    }

    const display = useMemo(() => {
        let displayValue = 'None'
        if (localAxisFormat) {
            displayValue = aggregationDisplayMap[localAxisFormat]
        }
        if (localAxisPrefix?.length) {
            displayValue = `prefix: ${localAxisPrefix}`
        }
        if (localAxisPostfix?.length) {
            displayValue = `postfix: ${localAxisPostfix}`
        }
        return displayValue
    }, [localAxisFormat, localAxisPrefix, localAxisPostfix])

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
                                    onClick={() => handleChange({ format: value, close: true })}
                                    status="stealth"
                                    active={value === localAxisFormat}
                                    fullWidth
                                >
                                    {label}
                                </LemonButton>
                            ))}
                            {!!featureFlags[FEATURE_FLAGS.CURRENCY_UNITS] && (
                                <>
                                    <LemonDivider />
                                    <PureField label={'prefix:'}>
                                        <LemonInput
                                            value={localAxisPrefix}
                                            onChange={(prefix) => handleChange({ prefix })}
                                            onPressEnter={(prefix) => handleChange({ prefix, close: true })}
                                        />
                                    </PureField>
                                    <PureField label={'postfix:'}>
                                        <LemonInput
                                            value={localAxisPostfix}
                                            onChange={(postfix) => handleChange({ postfix })}
                                            onPressEnter={(postfix) => handleChange({ postfix, close: true })}
                                        />
                                    </PureField>
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
