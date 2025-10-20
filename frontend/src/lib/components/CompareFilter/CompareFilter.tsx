import { useEffect, useState } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { dateFromToText } from 'lib/utils'

import { CompareFilter as CompareFilterType } from '~/queries/schema/schema-general'

type CompareFilterProps = {
    compareFilter?: CompareFilterType | null
    updateCompareFilter: (compareFilter: CompareFilterType) => void
    disabled?: boolean
    disableReason?: string | null
}

export function CompareFilter({
    compareFilter,
    updateCompareFilter,
    disabled,
    disableReason,
}: CompareFilterProps): JSX.Element | null {
    // This keeps the state of the rolling date range filter, even when different drop down options are selected
    // The default value for this is one month
    const [tentativeCompareTo, setTentativeCompareTo] = useState<string>(compareFilter?.compare_to || '-1m')

    const { isWindowLessThan } = useWindowSize()

    useEffect(() => {
        const newCompareTo = compareFilter?.compare_to
        if (!!newCompareTo && tentativeCompareTo !== newCompareTo) {
            setTentativeCompareTo(newCompareTo)
        }
    }, [compareFilter?.compare_to]) // oxlint-disable-line react-hooks/exhaustive-deps

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
            icon={<IconClock />}
            onSelect={(newValue) => {
                if (newValue === 'compareTo') {
                    updateCompareFilter({ compare: true, compare_to: tentativeCompareTo })
                }
            }}
            renderButtonContent={(leaf) => {
                if (!leaf) {
                    return 'Compare to'
                }

                const isHugeScreen = !isWindowLessThan('2xl')
                if (leaf.value === 'compareTo') {
                    return isHugeScreen
                        ? `Compare to ${dateFromToText(tentativeCompareTo)} earlier`
                        : `${dateFromToText(tentativeCompareTo)} earlier`
                } else if (leaf.value === 'previous') {
                    return isHugeScreen ? 'Compare to previous period' : 'Previous period'
                } else if (leaf.value === 'none') {
                    return isHugeScreen ? 'No comparison between periods' : 'No comparison'
                }

                // Should never happen
                return 'Compare to'
            }}
            value={value}
            dropdownMatchSelectWidth={false}
            onChange={(value) => {
                if (value === 'none') {
                    updateCompareFilter({ compare: false, compare_to: undefined })
                } else if (value === 'previous') {
                    updateCompareFilter({ compare: true, compare_to: undefined })
                }
            }}
            data-attr="compare-filter"
            options={options}
            size="small"
            disabled={disabled}
            disabledReason={disableReason}
        />
    )
}
