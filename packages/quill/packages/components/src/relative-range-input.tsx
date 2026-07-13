import { Minus, Plus } from 'lucide-react'
import * as React from 'react'

import {
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupNumberInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    cn,
} from '@posthog/quill-primitives'

export type RelativeRangeUnit = 'minutes' | 'hours' | 'days' | 'weeks' | 'months' | 'years'

export interface RelativeRangeValue {
    count: number
    unit: RelativeRangeUnit
}

export interface RelativeRangeInputProps {
    value: RelativeRangeValue
    onChange: (value: RelativeRangeValue) => void
    /** Units offered in the dropdown. Defaults to hours through months. */
    units?: RelativeRangeUnit[]
    min?: number
    max?: number
    className?: string
}

const DEFAULT_UNITS: RelativeRangeUnit[] = ['hours', 'days', 'weeks', 'months']

function unitLabel(unit: RelativeRangeUnit, count: number): string {
    return count === 1 ? unit.slice(0, -1) : unit
}

/** A "N units" duration control: stepper + unit dropdown. The host provides surrounding
 * words ("Last …") and maps the value to its own range vocabulary. */
export function RelativeRangeInput({
    value,
    onChange,
    units = DEFAULT_UNITS,
    min = 1,
    max = 999,
    className,
}: RelativeRangeInputProps): React.ReactElement {
    const clamp = (n: number): number => Math.min(max, Math.max(min, n))
    const setCount = (count: number | null): void => {
        if (count !== null && !Number.isNaN(count)) {
            onChange({ ...value, count: clamp(count) })
        }
    }

    return (
        <div className={cn('flex items-center gap-2', className)}>
            <InputGroup className="w-24">
                <InputGroupAddon align="inline-start">
                    <InputGroupButton
                        size="icon-xs"
                        aria-label="Decrease"
                        disabled={value.count <= min}
                        onClick={() => setCount(value.count - 1)}
                    >
                        <Minus />
                    </InputGroupButton>
                </InputGroupAddon>
                <InputGroupNumberInput
                    aria-label="Count"
                    value={value.count}
                    min={min}
                    max={max}
                    onValueChange={setCount}
                />
                <InputGroupAddon align="inline-end">
                    <InputGroupButton
                        size="icon-xs"
                        aria-label="Increase"
                        disabled={value.count >= max}
                        onClick={() => setCount(value.count + 1)}
                    >
                        <Plus />
                    </InputGroupButton>
                </InputGroupAddon>
            </InputGroup>
            <Select
                value={value.unit}
                onValueChange={(unit) => onChange({ ...value, unit: unit as RelativeRangeUnit })}
            >
                <SelectTrigger size="sm" className="w-auto gap-1" aria-label="Unit">
                    <SelectValue>{(unit: RelativeRangeUnit) => unitLabel(unit, value.count)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                    {units.map((unit) => (
                        <SelectItem key={unit} value={unit}>
                            {unitLabel(unit, value.count)}
                        </SelectItem>
                    ))}
                </SelectContent>
            </Select>
        </div>
    )
}
