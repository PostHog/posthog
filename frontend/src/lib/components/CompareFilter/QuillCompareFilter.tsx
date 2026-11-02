import { useId, useState } from 'react'

import { IconClock } from '@posthog/icons'
import {
    Button,
    Label,
    Popover,
    PopoverContent,
    PopoverTrigger,
    RadioGroup,
    RadioGroupItem,
    SelectTriggerIcon,
    Text,
} from '@posthog/quill'

import { dateRangeForSelection, selectionForDateRange } from 'lib/components/DateFilter/dateRangeSelection'
import { RelativeRangeInput, type RelativeRangeValue } from 'lib/components/DateFilter/RelativeRangeInput'

export type CompareFilterValue = 'inherit' | 'none' | 'previous' | 'compareTo'

export interface CompareFilterOption {
    value: CompareFilterValue
    label: string
}

export interface QuillCompareFilterProps {
    value: CompareFilterValue
    label: string
    options: CompareFilterOption[]
    tentativeCompareTo: string
    onSelect: (value: CompareFilterValue) => void
    onCompareToChange: (compareTo: string) => void
    disabled?: boolean
    disabledReason?: string | null
    tooltip?: string | null
    fullWidth?: boolean
}

const COMPARE_TO_UNITS: RelativeRangeValue['unit'][] = ['hours', 'days', 'weeks', 'months', 'years']

function relativeRangeFor(compareTo: string): RelativeRangeValue {
    const selection = selectionForDateRange(compareTo, null)
    return selection.kind === 'rolling'
        ? { count: selection.count, unit: selection.unit }
        : { count: 1, unit: 'months' }
}

export function QuillCompareFilter({
    value,
    label,
    options,
    tentativeCompareTo,
    onSelect,
    onCompareToChange,
    disabled,
    disabledReason,
    tooltip,
    fullWidth,
}: QuillCompareFilterProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const id = useId()

    return (
        <Popover open={open} onOpenChange={setOpen}>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        disabled={disabled}
                        disabledReason={disabledReason}
                        tooltip={tooltip}
                        className={fullWidth ? 'w-full' : undefined}
                        data-attr="compare-filter"
                    />
                }
            >
                <IconClock />
                <span className="text-nowrap">{label}</span>
                <SelectTriggerIcon />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto">
                <RadioGroup
                    value={value}
                    onValueChange={(next) => {
                        onSelect(next as CompareFilterValue)
                        if (next !== 'compareTo') {
                            setOpen(false)
                        }
                    }}
                >
                    {options.map((option) => (
                        <div key={option.value} className="flex items-center gap-2">
                            <RadioGroupItem value={option.value} id={`${id}-${option.value}`} />
                            <Label htmlFor={`${id}-${option.value}`} className="font-normal whitespace-nowrap">
                                {option.label}
                            </Label>
                            {option.value === 'compareTo' && (
                                <>
                                    <RelativeRangeInput
                                        value={relativeRangeFor(tentativeCompareTo)}
                                        units={COMPARE_TO_UNITS}
                                        onChange={(range) =>
                                            onCompareToChange(
                                                dateRangeForSelection({ kind: 'rolling', ...range }).date_from ??
                                                    tentativeCompareTo
                                            )
                                        }
                                    />
                                    <Text size="xs" render={<span />}>
                                        earlier
                                    </Text>
                                </>
                            )}
                        </div>
                    ))}
                </RadioGroup>
            </PopoverContent>
        </Popover>
    )
}
