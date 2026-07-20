import { IconMinus, IconPlus } from '@posthog/icons'
import {
    cn,
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupNumberInput,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

export type RelativeRangeUnit = 'minutes' | 'hours' | 'days' | 'weeks' | 'months' | 'years'

export interface RelativeRangeValue {
    count: number
    unit: RelativeRangeUnit
}

export interface RelativeRangeInputProps {
    value: RelativeRangeValue
    onChange: (value: RelativeRangeValue) => void
    units?: RelativeRangeUnit[]
    min?: number
    max?: number
    className?: string
    /** Extra props for the unit dropdown surface (portaled to <body>) — e.g. skin opt-in data attributes. */
    selectContentProps?: React.HTMLAttributes<HTMLDivElement>
}

const DEFAULT_UNITS: RelativeRangeUnit[] = ['hours', 'days', 'weeks', 'months', 'years']

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
    selectContentProps,
}: RelativeRangeInputProps): JSX.Element {
    const clamp = (n: number): number => Math.min(max, Math.max(min, n))
    const setCount = (count: number | null): void => {
        if (count !== null && !Number.isNaN(count)) {
            onChange({ ...value, count: clamp(count) })
        }
    }

    return (
        <div className={cn('flex items-center gap-2', className)}>
            <InputGroup className="w-28">
                <InputGroupAddon align="inline-start">
                    <InputGroupButton
                        size="icon-xs"
                        aria-label="Decrease"
                        disabled={value.count <= min}
                        onClick={() => setCount(value.count - 1)}
                    >
                        <IconMinus />
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
                        <IconPlus />
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
                <SelectContent {...selectContentProps}>
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
