import {
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { VariableCalendar } from './VariableCalendar'
import { RELATIVE_DATE_UNITS } from './VariableFields'
import {
    RelativeDateUnit,
    formatRelativeDateValue,
    isRelativeDateValue,
    normalizeRelativeDateAmount,
    parseRelativeDateValue,
} from './variableUtils'

interface QuillVariableDateFieldProps {
    value: string
    onChange: (value: string) => void
    onApply: (value: string) => void
}

export function QuillVariableDateField({ value, onChange, onApply }: QuillVariableDateFieldProps): JSX.Element {
    const isRelative = isRelativeDateValue(value)
    const relativeValue = parseRelativeDateValue(value) ?? { amount: 0, unit: 'd' as RelativeDateUnit }

    return (
        <div className="flex grow flex-col gap-2">
            <ToggleGroup
                className="w-full"
                value={[isRelative ? 'relative' : 'fixed']}
                onValueChange={(next: string[]) => {
                    if (next[0]) {
                        onChange(next[0] === 'relative' ? '-0d' : dayjs().format('YYYY-MM-DD HH:mm:00'))
                    }
                }}
            >
                <ToggleGroupItem value="fixed" className="flex-1">
                    Fixed date
                </ToggleGroupItem>
                <ToggleGroupItem value="relative" className="flex-1">
                    Relative date
                </ToggleGroupItem>
            </ToggleGroup>
            {isRelative ? (
                <>
                    <div className="flex items-center gap-2">
                        <Input
                            type="number"
                            min={0}
                            step={1}
                            className="w-20"
                            value={relativeValue.amount}
                            onChange={(event) =>
                                onChange(`-${normalizeRelativeDateAmount(event.target.value)}${relativeValue.unit}`)
                            }
                        />
                        <Select
                            value={relativeValue.unit}
                            onValueChange={(unit) =>
                                onChange(`-${relativeValue.amount}${(unit as RelativeDateUnit) ?? 'd'}`)
                            }
                        >
                            <SelectTrigger className="grow" aria-label="Unit">
                                <SelectValue>
                                    {(unit: RelativeDateUnit) =>
                                        RELATIVE_DATE_UNITS.find((option) => option.value === unit)?.label
                                    }
                                </SelectValue>
                            </SelectTrigger>
                            <SelectContent>
                                {RELATIVE_DATE_UNITS.map((option) => (
                                    <SelectItem key={option.value} value={option.value}>
                                        {option.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <span className="whitespace-nowrap text-muted-foreground">ago</span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                        Current value: <span>{formatRelativeDateValue(value)}</span>
                    </span>
                </>
            ) : (
                <VariableCalendar
                    value={dayjs(value)}
                    rawValue={value}
                    updateVariable={(date) => {
                        onChange(date)
                        onApply(date)
                    }}
                />
            )}
        </div>
    )
}
