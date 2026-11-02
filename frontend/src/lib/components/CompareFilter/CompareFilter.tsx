import { useEffect, useState } from 'react'

import { IconClock } from '@posthog/icons'
import { LemonButtonProps, LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { RollingDateRangeFilter } from 'lib/components/DateFilter/RollingDateRangeFilter'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { dateFromToText } from 'lib/utils/dateFilters'

import { CompareFilter as CompareFilterType } from '~/queries/schema/schema-general'

import { type CompareFilterOption, type CompareFilterValue, QuillCompareFilter } from './QuillCompareFilter'

/** Shared `disableReason` for callers that turn off comparison once the date range is "All time". */
export const COMPARE_ALL_TIME_DISABLED_REASON =
    "All time starts at your first event, so there's no earlier period to compare to. Pick a date range to compare."

type CompareFilterProps = {
    allowCustomComparison?: boolean
    compareFilter?: CompareFilterType | null
    updateCompareFilter: (compareFilter: CompareFilterType) => void
    disabled?: boolean
    disableReason?: string | null
    /** Shown on hover, e.g. the resolved comparison date range */
    tooltip?: string | null
    /** Label for a 4th option that lets the caller fall back to some other setting. The option only renders when `onInherit` is also passed. */
    inheritLabel?: string
    /** Called instead of `updateCompareFilter` when the inherit option is selected. Selected whenever `compareFilter` is null/undefined. Requires `inheritLabel`. */
    onInherit?: () => void
    fullWidth?: boolean
    size?: LemonButtonProps['size']
}

export function CompareFilter({
    compareFilter,
    updateCompareFilter,
    disabled,
    disableReason,
    tooltip,
    allowCustomComparison = true,
    inheritLabel,
    onInherit,
    fullWidth,
    size = 'small',
}: CompareFilterProps): JSX.Element | null {
    // This keeps the state of the rolling date range filter, even when different drop down options are selected
    // The default value for this is one month
    const [tentativeCompareTo, setTentativeCompareTo] = useState<string>(compareFilter?.compare_to || '-1m')

    const { isWindowLessThan } = useWindowSize()
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(() => {
        const newCompareTo = compareFilter?.compare_to
        if (!!newCompareTo && tentativeCompareTo !== newCompareTo) {
            setTentativeCompareTo(newCompareTo)
        }
    }, [compareFilter?.compare_to]) // oxlint-disable-line react-hooks/exhaustive-deps

    let value: CompareFilterValue = 'none'
    if (onInherit && inheritLabel && compareFilter == null) {
        value = 'inherit'
    } else if (compareFilter?.compare) {
        if (compareFilter?.compare_to) {
            value = 'compareTo'
        } else {
            value = 'previous'
        }
    }

    const selectValue = (newValue: CompareFilterValue): void => {
        if (newValue === 'inherit') {
            onInherit?.()
        } else if (newValue === 'none') {
            updateCompareFilter({ compare: false, compare_to: undefined })
        } else if (newValue === 'previous') {
            updateCompareFilter({ compare: true, compare_to: undefined })
        } else {
            updateCompareFilter({ compare: true, compare_to: tentativeCompareTo })
        }
    }

    const isHugeScreen = size !== 'xsmall' && !isWindowLessThan('2xl')
    const labelFor = (leafValue: CompareFilterValue): string => {
        if (leafValue === 'compareTo') {
            return isHugeScreen
                ? `Compare to ${dateFromToText(tentativeCompareTo)} earlier`
                : `${dateFromToText(tentativeCompareTo)} earlier`
        } else if (leafValue === 'previous') {
            return isHugeScreen ? 'Compare to previous period' : 'Previous period'
        } else if (leafValue === 'none') {
            return isHugeScreen ? 'No comparison between periods' : 'No comparison'
        }
        return inheritLabel ?? ''
    }

    if (todayRailNav) {
        const quillOptions: CompareFilterOption[] = [
            ...(onInherit && inheritLabel ? [{ value: 'inherit' as const, label: inheritLabel }] : []),
            { value: 'none', label: 'No comparison between periods' },
            { value: 'previous', label: 'Compare to previous period' },
            ...(allowCustomComparison ? [{ value: 'compareTo' as const, label: 'Compare to' }] : []),
        ]
        return (
            <QuillCompareFilter
                value={value}
                label={labelFor(value)}
                options={quillOptions}
                tentativeCompareTo={tentativeCompareTo}
                onSelect={selectValue}
                onCompareToChange={(compare_to) => {
                    setTentativeCompareTo(compare_to)
                    updateCompareFilter({ compare: true, compare_to })
                }}
                disabled={disabled}
                disabledReason={disableReason}
                tooltip={tooltip}
                fullWidth={fullWidth}
            />
        )
    }

    const options: LemonSelectOptionLeaf<CompareFilterValue>[] = [
        ...(onInherit && inheritLabel
            ? [
                  {
                      value: 'inherit' as const,
                      label: inheritLabel,
                  },
              ]
            : []),
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

    return (
        <LemonSelect
            icon={<IconClock />}
            onSelect={(newValue) => {
                if (newValue === 'compareTo') {
                    selectValue(newValue)
                }
            }}
            renderButtonContent={(leaf) => (leaf?.value ? labelFor(leaf.value) : 'Compare to')}
            value={value}
            dropdownMatchSelectWidth={false}
            onChange={(newValue) => {
                if (newValue && newValue !== 'compareTo') {
                    selectValue(newValue)
                }
            }}
            data-attr="compare-filter"
            options={options.filter((option) => allowCustomComparison || option.value !== 'compareTo')}
            size={size}
            fullWidth={fullWidth}
            disabled={disabled}
            disabledReason={disableReason}
            tooltip={tooltip}
        />
    )
}
