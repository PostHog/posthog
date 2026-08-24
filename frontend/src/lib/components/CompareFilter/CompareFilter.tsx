import { ReactNode, useEffect, useState } from 'react'

import { IconCheck, IconClock } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { dateFromToText } from 'lib/utils/dateFilters'

import { CompareFilter as CompareFilterType } from '~/queries/schema/schema-general'

const NO_COMPARISON_LABEL = 'No comparison'
const PREVIOUS_PERIOD_LABEL = 'Compare to previous period'
const PREVIOUS_PERIOD_SHORT_LABEL = 'Previous period'

type CompareFilterProps = {
    compareFilter?: CompareFilterType | null
    updateCompareFilter: (compareFilter: CompareFilterType) => void
    disabled?: boolean
    disableReason?: string | null
    /** Shown on hover, e.g. the resolved comparison date range */
    tooltip?: string | null
}

export function CompareFilter({
    compareFilter,
    updateCompareFilter,
    disabled,
    disableReason,
    tooltip,
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

    let value = 'none'
    if (compareFilter?.compare) {
        if (compareFilter?.compare_to) {
            value = 'compareTo'
        } else {
            value = 'previous'
        }
    }

    // A trailing check marks the selected row in the dropdown. `labelInMenu` keeps the
    // marker out of the collapsed button, which renders its own content separately.
    const withSelectedMarker = (label: ReactNode, selected: boolean): JSX.Element => (
        <span className="flex flex-1 items-center justify-between gap-2">
            {label}
            {selected && <IconCheck />}
        </span>
    )

    const options = [
        {
            value: 'none',
            label: NO_COMPARISON_LABEL,
            labelInMenu: withSelectedMarker(NO_COMPARISON_LABEL, value === 'none'),
        },
        {
            value: 'previous',
            label: PREVIOUS_PERIOD_LABEL,
            labelInMenu: withSelectedMarker(PREVIOUS_PERIOD_LABEL, value === 'previous'),
        },
        {
            value: 'compareTo',
            label: 'compareTo',
            labelInMenu: withSelectedMarker(
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
                />,
                value === 'compareTo'
            ),
        },
    ]

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
                    return isHugeScreen ? PREVIOUS_PERIOD_LABEL : PREVIOUS_PERIOD_SHORT_LABEL
                } else if (leaf.value === 'none') {
                    return NO_COMPARISON_LABEL
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
            tooltip={tooltip}
        />
    )
}
