import { useActions, useValues } from 'kea'
import { CustomUnitModal } from 'lib/components/UnitPicker/CustomUnitModal'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { useMemo, useRef, useState } from 'react'
import { AggregationAxisFormat, INSIGHT_UNIT_OPTIONS } from 'scenes/insights/aggregationAxisFormat'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

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

export function UnitPicker(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { trendsFilter, display } = useValues(insightVizDataLogic(insightProps))
    const { updateInsightFilter } = useActions(insightVizDataLogic(insightProps))

    const { reportAxisUnitsChanged } = useActions(eventUsageLogic)

    const [isVisible, setIsVisible] = useState(false)
    const [localAxisFormat, setLocalAxisFormat] = useState(trendsFilter?.aggregation_axis_format || undefined)
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

        updateInsightFilter({
            aggregation_axis_format: format,
            aggregation_axis_prefix: prefix,
            aggregation_axis_postfix: postfix,
        })

        reportAxisUnitsChanged({
            format,
            prefix,
            postfix,
            display,
            unitIsSet: !!prefix || !!postfix || (format && format !== 'numeric'),
        })

        setIsVisible(false)
        setCustomUnitModal(null)
    }

    const displayValue = useMemo(() => {
        let displayValue = 'None'
        if (localAxisFormat) {
            displayValue = aggregationDisplayMap[localAxisFormat]
        }
        if (trendsFilter?.aggregation_axis_prefix?.length) {
            displayValue = `Prefix: ${trendsFilter?.aggregation_axis_prefix}`
        }
        if (trendsFilter?.aggregation_axis_postfix?.length) {
            displayValue = `Postfix: ${trendsFilter?.aggregation_axis_postfix}`
        }
        return displayValue
    }, [localAxisFormat, trendsFilter])

    return (
        <div className="flex-1 mb-2.5 mx-2">
            <CustomUnitModal
                formativeElement={customUnitModal}
                isOpen={customUnitModal !== null}
                onSave={handleChange}
                trendsFilter={trendsFilter}
                onClose={() => setCustomUnitModal(null)}
                overlayRef={(ref) => (customUnitModalRef.current = ref)}
            />
            <LemonButtonWithDropdown
                onClick={() => setIsVisible(!isVisible)}
                size={'small'}
                type={'secondary'}
                status="stealth"
                data-attr="chart-aggregation-axis-format"
                fullWidth
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
                                    active={!!trendsFilter?.aggregation_axis_prefix}
                                    fullWidth
                                >
                                    Custom prefix
                                    {trendsFilter?.aggregation_axis_prefix
                                        ? `: ${trendsFilter?.aggregation_axis_prefix}...`
                                        : '...'}
                                </LemonButton>
                                <LemonButton
                                    onClick={() => setCustomUnitModal('postfix')}
                                    status="stealth"
                                    active={!!trendsFilter?.aggregation_axis_postfix}
                                    fullWidth
                                >
                                    Custom postfix
                                    {trendsFilter?.aggregation_axis_postfix
                                        ? `: ${trendsFilter?.aggregation_axis_postfix}...`
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
