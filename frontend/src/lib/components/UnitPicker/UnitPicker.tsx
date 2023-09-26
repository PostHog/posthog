import { AggregationAxisFormat, INSIGHT_UNIT_OPTIONS } from 'scenes/insights/aggregationAxisFormat'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { useMemo, useRef, useState } from 'react'
import { useActions, useValues } from 'kea'
import { useKeyboardHotkeys } from 'lib/hooks/useKeyboardHotkeys'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { CustomUnitModal } from 'lib/components/UnitPicker/CustomUnitModal'
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
    const [localAxisFormat, setLocalAxisFormat] = useState(trendsFilter?.aggregationAxisFormat || undefined)
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
        setCustomUnitModal(null)
    }

    const displayValue = useMemo(() => {
        let displayValue = 'None'
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

    return (
        <div className="flex flex-1 pt-1.5 pb-2 pr-2">
            <CustomUnitModal
                formativeElement={customUnitModal}
                isOpen={customUnitModal !== null}
                onSave={handleChange}
                trendsFilter={trendsFilter}
                onClose={() => setCustomUnitModal(null)}
                overlayRef={(ref) => (customUnitModalRef.current = ref)}
            />
            <LemonButtonWithDropdown
                className="flex flex-1 ml-2"
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
                                    active={!!trendsFilter?.aggregationAxisPrefix}
                                    fullWidth
                                >
                                    Custom prefix
                                    {trendsFilter?.aggregationAxisPrefix
                                        ? `: ${trendsFilter?.aggregationAxisPrefix}...`
                                        : '...'}
                                </LemonButton>
                                <LemonButton
                                    onClick={() => setCustomUnitModal('postfix')}
                                    status="stealth"
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
