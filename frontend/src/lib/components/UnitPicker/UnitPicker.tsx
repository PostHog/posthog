import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { AggregationAxisFormat, INSIGHT_UNIT_OPTIONS } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { unitPickerModalLogic } from './unitPickerModalLogic'

const aggregationDisplayMap = INSIGHT_UNIT_OPTIONS.reduce<Record<AggregationAxisFormat, React.ReactNode>>(
    (acc, option) => {
        acc[option.value] = option.label
        return acc
    },
    {} as Record<AggregationAxisFormat, React.ReactNode>
)

export interface HandleUnitChange {
    format?: AggregationAxisFormat
    prefix?: string
    postfix?: string
    close?: boolean
}

export function UnitPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter, display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))
    const { showCustomUnitModal } = useActions(unitPickerModalLogic)

    const { reportAxisUnitsChanged } = useActions(eventUsageLogic)

    const [isVisible, setIsVisible] = useState(false)
    const [localAxisFormat, setLocalAxisFormat] = useState(trendsFilter?.aggregationAxisFormat || undefined)

    useKeyboardHotkeys(
        {
            escape: {
                action: function () {
                    setIsVisible(false)
                },
            },
        },
        []
    )

    const handleChange = ({ format, prefix, postfix }: HandleUnitChange): void => {
        setLocalAxisFormat(format)

        updateInsightFilter({
            aggregationAxisFormat: format,
            aggregationAxisPrefix: prefix,
            aggregationAxisPostfix: postfix,
        })

        reportAxisUnitsChanged({
            format,
            prefix,
            postfix,
            display,
            unitIsSet: !!prefix || !!postfix || (format && format !== 'numeric'),
        })

        setIsVisible(false)
    }

    const displayValue = useMemo(() => {
        let displayValue: React.ReactNode = 'None'
        if (localAxisFormat) {
            displayValue = aggregationDisplayMap[localAxisFormat]
        }
        if (trendsFilter?.aggregationAxisPrefix?.length) {
            displayValue = `Prefix: ${trendsFilter?.aggregationAxisPrefix}`
        }
        if (trendsFilter?.aggregationAxisPostfix?.length) {
            displayValue = `Postfix: ${trendsFilter?.aggregationAxisPostfix}`
        }
        return displayValue
    }, [localAxisFormat, trendsFilter])

    const handleCustomPrefix = (): void => {
        showCustomUnitModal({
            type: 'prefix',
            currentValue: trendsFilter?.aggregationAxisPrefix || '',
            callback: (value: string) => handleChange({ prefix: value }),
        })
    }

    const handleCustomPostfix = (): void => {
        showCustomUnitModal({
            type: 'postfix',
            currentValue: trendsFilter?.aggregationAxisPostfix || '',
            callback: (value: string) => handleChange({ postfix: value }),
        })
    }

    return (
        <div className="flex-1 mb-2.5 mx-2">
            <LemonButtonWithDropdown
                onClick={() => setIsVisible(!isVisible)}
                size="small"
                type="secondary"
                data-attr="chart-aggregation-axis-format"
                fullWidth
                dropdown={{
                    onClickOutside: () => setIsVisible(false),
                    visible: isVisible,
                    overlay: (
                        <>
                            {INSIGHT_UNIT_OPTIONS.map(({ value, label }, index) => (
                                <LemonButton
                                    key={index}
                                    onClick={() => handleChange({ format: value })}
                                    active={value === localAxisFormat}
                                    fullWidth
                                >
                                    {label}
                                </LemonButton>
                            ))}

                            <>
                                <LemonDivider />
                                <LemonButton
                                    onClick={handleCustomPrefix}
                                    active={!!trendsFilter?.aggregationAxisPrefix}
                                    fullWidth
                                >
                                    Custom prefix
                                    {trendsFilter?.aggregationAxisPrefix
                                        ? `: ${trendsFilter?.aggregationAxisPrefix}...`
                                        : '...'}
                                </LemonButton>
                                <LemonButton
                                    onClick={handleCustomPostfix}
                                    active={!!trendsFilter?.aggregationAxisPostfix}
                                    fullWidth
                                >
                                    Custom postfix
                                    {trendsFilter?.aggregationAxisPostfix
                                        ? `: ${trendsFilter?.aggregationAxisPostfix}...`
                                        : '...'}
                                </LemonButton>
                            </>
                        </>
                    ),
                    placement: 'bottom-start',
                    actionable: true,
                    closeOnClickInside: false,
                }}
            >
                {displayValue}
            </LemonButtonWithDropdown>
        </div>
    )
}
