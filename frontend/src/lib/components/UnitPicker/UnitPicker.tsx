import { AggregationAxisFormat, INSIGHT_UNIT_OPTIONS, axisLabel } from 'scenes/insights/aggregationAxisFormat'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useMemo, useRef, useState } from 'react'
import { ItemMode, TrendsFilterType } from '~/types'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { CustomUnitModal } from 'lib/components/UnitPicker/CustomUnitModal'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'

interface UnitPickerProps {
    filters: TrendsFilterType
    setFilters: (filters: Partial<TrendsFilterType>, insightMode?: ItemMode | undefined) => void
}

const aggregationDisplayMap = INSIGHT_UNIT_OPTIONS.reduce((acc, option) => {
    acc[option.value] = option.label
    return acc
}, {})

export interface HandleUnitChange {
    format?: AggregationAxisFormat
    prefix?: string
    postfix?: string
    close?: boolean
}

export function UnitPicker({ filters, setFilters }: UnitPickerProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { updateInsightFilter } = useActions(insightDataLogic(insightProps))
    const { reportAxisUnitsChanged } = useActions(eventUsageLogic)
    const [isVisible, setIsVisible] = useState(false)
    const [localAxisFormat, setLocalAxisFormat] = useState(filters.aggregation_axis_format || undefined)
    const [customUnitModal, setCustomUnitModal] = useState<'prefix' | 'postfix' | null>(null)

    const customUnitModalRef = useRef<HTMLDivElement | null>(null)

    useKeyboardHotkeys(
        {
            escape: {
                action: function () {
                    setCustomUnitModal(null)
                    setIsVisible(false)
                },
            },
        },
        []
    )

    const handleChange = ({ format, prefix, postfix }: HandleUnitChange): void => {
        setLocalAxisFormat(format)

        setFilters({
            ...filters,
            aggregation_axis_format: format,
            aggregation_axis_prefix: prefix,
            aggregation_axis_postfix: postfix,
        })

        updateInsightFilter({
            aggregation_axis_format: format,
            aggregation_axis_prefix: prefix,
            aggregation_axis_postfix: postfix,
        })

        reportAxisUnitsChanged({
            format,
            prefix,
            postfix,
            display: filters.display,
            unitIsSet: !!prefix || !!postfix || (format && format !== 'numeric'),
        })

        setIsVisible(false)
        setCustomUnitModal(null)
    }

    const display = useMemo(() => {
        let displayValue = 'None'
        if (localAxisFormat) {
            displayValue = aggregationDisplayMap[localAxisFormat]
        }
        if (filters.aggregation_axis_prefix?.length) {
            displayValue = `Prefix: ${filters.aggregation_axis_prefix}`
        }
        if (filters.aggregation_axis_postfix?.length) {
            displayValue = `Postfix: ${filters.aggregation_axis_postfix}`
        }
        return displayValue
    }, [localAxisFormat, filters])

    return (
        <>
            <span>{axisLabel(filters.display)}</span>
            <CustomUnitModal
                formativeElement={customUnitModal}
                isOpen={customUnitModal !== null}
                onSave={handleChange}
                filters={filters}
                onClose={() => setCustomUnitModal(null)}
                overlayRef={(ref) => (customUnitModalRef.current = ref)}
            />
            <LemonButtonWithDropdown
                onClick={() => setIsVisible(!isVisible)}
                size={'small'}
                type={'secondary'}
                status="stealth"
                data-attr="chart-aggregation-axis-format"
                dropdown={{
                    onClickOutside: () => setIsVisible(false),
                    additionalRefs: [customUnitModalRef],
                    visible: isVisible,
                    overlay: (
                        <>
                            {INSIGHT_UNIT_OPTIONS.map(({ value, label }, index) => (
                                <LemonButton
                                    key={index}
                                    onClick={() => handleChange({ format: value })}
                                    status="stealth"
                                    active={value === localAxisFormat}
                                    fullWidth
                                >
                                    {label}
                                </LemonButton>
                            ))}

                            <>
                                <LemonDivider />
                                <LemonButton
                                    onClick={() => setCustomUnitModal('prefix')}
                                    status="stealth"
                                    active={!!filters.aggregation_axis_prefix}
                                    fullWidth
                                >
                                    Custom prefix
                                    {!!filters.aggregation_axis_prefix
                                        ? `: ${filters.aggregation_axis_prefix}...`
                                        : '...'}
                                </LemonButton>
                                <LemonButton
                                    onClick={() => setCustomUnitModal('postfix')}
                                    status="stealth"
                                    active={!!filters.aggregation_axis_postfix}
                                    fullWidth
                                >
                                    Custom postfix
                                    {!!filters.aggregation_axis_postfix
                                        ? `: ${filters.aggregation_axis_postfix}...`
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
                {display}
            </LemonButtonWithDropdown>
        </>
    )
}
