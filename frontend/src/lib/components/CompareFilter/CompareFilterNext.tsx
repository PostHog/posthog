import { type ChangeEvent, useState } from 'react'

import { IconClock } from '@posthog/icons'
import {
    Button,
    Input,
    Popover,
    PopoverContent,
    PopoverTrigger,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { useWindowSize } from 'lib/hooks/useWindowSize'
import { dateFromToText } from 'lib/utils/dateFilters'

import { CompareFilter as CompareFilterType } from '~/queries/schema/schema-general'

const COMPARE_UNITS: Record<string, string> = {
    d: 'days',
    w: 'weeks',
    m: 'months',
    y: 'years',
}

const COMPARE_TO_REGEX = /^-(\d+)([dwmy])$/
const DEFAULT_COMPARE_COUNT = '1'
const DEFAULT_COMPARE_UNIT = 'm'

type CompareFilterNextProps = {
    compareFilter?: CompareFilterType | null
    updateCompareFilter: (compareFilter: CompareFilterType) => void
    disabled?: boolean
    disableReason?: string | null
    /** Shown on hover, e.g. the resolved comparison date range */
    tooltip?: string | null
}

export function CompareFilterNext({
    compareFilter,
    updateCompareFilter,
    disabled,
    disableReason,
    tooltip,
}: CompareFilterNextProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [compareCount, setCompareCount] = useState<string>(DEFAULT_COMPARE_COUNT)
    const [compareUnit, setCompareUnit] = useState<string>(DEFAULT_COMPARE_UNIT)

    const { isWindowLessThan } = useWindowSize()
    const isHugeScreen = !isWindowLessThan('2xl')

    const compareTo = compareFilter?.compare_to
    const value = compareFilter?.compare ? (compareTo ? 'compareTo' : 'previous') : 'none'

    let label: string
    if (value === 'compareTo' && compareTo) {
        label = isHugeScreen
            ? `Compare to ${dateFromToText(compareTo)} earlier`
            : `${dateFromToText(compareTo)} earlier`
    } else if (value === 'previous') {
        label = isHugeScreen ? 'Compare to previous period' : 'Previous period'
    } else {
        label = isHugeScreen ? 'No comparison between periods' : 'No comparison'
    }

    const handleOpenChange = (nextOpen: boolean): void => {
        if (nextOpen) {
            const compareToMatch = COMPARE_TO_REGEX.exec(compareTo ?? '')
            setCompareCount(compareToMatch?.[1] ?? DEFAULT_COMPARE_COUNT)
            setCompareUnit(compareToMatch?.[2] ?? DEFAULT_COMPARE_UNIT)
        }
        setOpen(nextOpen)
    }

    const applyNone = (): void => {
        updateCompareFilter({ compare: false, compare_to: undefined })
        setOpen(false)
    }
    const applyPrevious = (): void => {
        updateCompareFilter({ compare: true, compare_to: undefined })
        setOpen(false)
    }
    const applyCompareTo = (): void => {
        const count = Math.max(1, parseInt(compareCount) || 1)
        updateCompareFilter({ compare: true, compare_to: `-${count}${compareUnit}` })
        setOpen(false)
    }

    return (
        <Popover open={open} onOpenChange={handleOpenChange}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        data-attr="compare-filter"
                        data-quill
                        disabled={disabled || !!disableReason}
                        title={disableReason ?? tooltip ?? undefined}
                    >
                        <IconClock />
                        {label}
                    </Button>
                }
            />
            <PopoverContent align="start" className="w-auto p-0 overflow-hidden">
                <div className="flex w-72 flex-col gap-px p-2">
                    <Button
                        variant="default"
                        size="sm"
                        left
                        className="w-full justify-start"
                        aria-selected={value === 'none'}
                        onClick={applyNone}
                        data-attr="compare-filter-none"
                    >
                        No comparison between periods
                    </Button>
                    <Button
                        variant="default"
                        size="sm"
                        left
                        className="w-full justify-start"
                        aria-selected={value === 'previous'}
                        onClick={applyPrevious}
                        data-attr="compare-filter-previous"
                    >
                        Compare to previous period
                    </Button>
                    <div className="flex items-center gap-1 px-2 py-1">
                        <span className="text-xs whitespace-nowrap">Compare to</span>
                        <Input
                            type="number"
                            min={1}
                            value={compareCount}
                            onChange={(e: ChangeEvent<HTMLInputElement>) =>
                                setCompareCount(e.target.value.replace(/[^0-9]/g, ''))
                            }
                            className="h-6 w-12"
                            aria-label="Comparison period count"
                            data-attr="compare-filter-compare-to-count"
                        />
                        <Select
                            value={compareUnit}
                            onValueChange={(unit: string | null) => setCompareUnit(unit ?? DEFAULT_COMPARE_UNIT)}
                            items={COMPARE_UNITS}
                        >
                            <SelectTrigger size="sm" aria-label="Comparison period unit">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {Object.entries(COMPARE_UNITS).map(([unitValue, unitLabel]) => (
                                    <SelectItem key={unitValue} value={unitValue}>
                                        {unitLabel}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <span className="text-xs whitespace-nowrap">earlier</span>
                        <Button
                            size="sm"
                            onClick={applyCompareTo}
                            aria-selected={value === 'compareTo'}
                            data-attr="compare-filter-compare-to-apply"
                        >
                            Apply
                        </Button>
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    )
}
