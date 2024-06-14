import { LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { dateFromToText } from 'lib/utils'
import { useEffect, useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

export function CompareFilter(): JSX.Element | null {
    const { insightProps, canEditInsight } = useValues(insightLogic)

    const { compareFilter, supportsCompare } = useValues(insightVizDataLogic(insightProps))
    const { updateCompareFilter } = useActions(insightVizDataLogic(insightProps))

    // This keeps the state of the rolling date range filter, even when different drop down options are selected
    // The default value for this is one month
    const [tentativeCompareTo, setTentativeCompareTo] = useState<string>(compareFilter?.compare_to || '-1m')

    const disabled: boolean = !canEditInsight || !supportsCompare

    useEffect(() => {
        const newCompareTo = compareFilter?.compare_to
        if (!!newCompareTo && tentativeCompareTo != newCompareTo) {
            setTentativeCompareTo(newCompareTo)
        }
    }, [compareFilter?.compare_to])

    // Hide compare filter control when disabled to avoid states where control is "disabled but checked"
    if (disabled) {
        return null
    }

    const options = [
        {
            value: 'none',
            label: 'No comparison between periods',
        },
        {
            value: 'previous',
            label: 'Compare to previous period',
        },
        {
            value: 'compareTo',
            label: (
                <RollingDateRangeFilter
                    isButton={false}
                    dateRangeFilterLabel="Compare to "
                    dateRangeFilterSuffixLabel=" earlier"
                    dateFrom={tentativeCompareTo}
                    selected={!!compareFilter?.compare && !!compareFilter?.compare_to}
                    inUse={true}
                    onChange={(compare_to) => {
                        updateCompareFilter({ compare: true, compare_to })
                    }}
                />
            ),
        },
    ]

    let value = 'none'
    if (compareFilter?.compare) {
        if (compareFilter?.compare_to) {
            value = 'compareTo'
        } else {
            value = 'previous'
        }
    }

    return (
        <LemonSelect
            onSelect={(newValue) => {
                if (newValue == 'compareTo') {
                    updateCompareFilter({ compare: true, compare_to: tentativeCompareTo })
                }
            }}
            renderButtonContent={(leaf) =>
                (leaf?.value == 'compareTo'
                    ? `Compare to ${dateFromToText(tentativeCompareTo)} earlier`
                    : leaf?.label) || 'Compare to'
            }
            value={value}
            dropdownMatchSelectWidth={false}
            onChange={(value) => {
                if (value == 'none') {
                    updateCompareFilter({ compare: false, compare_to: undefined })
                } else if (value == 'previous') {
                    updateCompareFilter({ compare: true, compare_to: undefined })
                }
            }}
            data-attr="compare-filter"
            options={options}
            size="small"
        />
    )
}
