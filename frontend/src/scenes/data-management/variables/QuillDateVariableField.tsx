import { useId, useState } from 'react'

import {
    DatePicker,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import {
    RelativeDateUnit,
    formatRelativeDateValue,
    isRelativeDateValue,
    normalizeRelativeDateAmount,
    parseRelativeDateValue,
} from '~/queries/nodes/DataVisualization/Components/Variables/variableUtils'
import { DateVariable } from '~/queries/nodes/DataVisualization/types'

const RELATIVE_DATE_UNITS: Array<{ value: RelativeDateUnit; label: string }> = [
    { value: 'h', label: 'hours' },
    { value: 'd', label: 'days' },
    { value: 'w', label: 'weeks' },
    { value: 'm', label: 'months' },
    { value: 'y', label: 'years' },
]

const DATE_FORMAT = 'YYYY-MM-DD'
const DATE_TIME_FORMAT = 'YYYY-MM-DD HH:mm:00'

const valueIncludesTime = (value: string): boolean => /\d{2}:\d{2}(:\d{2})?/.test(value)

export interface QuillDateVariableFieldProps {
    id?: string
    variable: DateVariable
    updateVariable: (variable: DateVariable) => void
}

/** Quill sibling of `DateField`, for the SQL variable edit page. Writes the same default values. */
export function QuillDateVariableField({ id, variable, updateVariable }: QuillDateVariableFieldProps): JSX.Element {
    const unitId = useId()
    const defaultValue = variable.default_value ?? ''
    const isRelative = isRelativeDateValue(defaultValue)
    const relativeValue = parseRelativeDateValue(defaultValue) ?? { amount: 0, unit: 'd' as RelativeDateUnit }
    const fixedDate = dayjs(defaultValue)
    const [includeTime, setIncludeTime] = useState(() => valueIncludesTime(defaultValue))

    return (
        <div className="flex flex-col gap-2">
            <ToggleGroup
                id={id}
                variant="outline"
                aria-label="Date mode"
                className="w-full"
                value={[isRelative ? 'relative' : 'fixed']}
                onValueChange={(next: string[]) => {
                    const mode = next[0]
                    if (!mode || mode === (isRelative ? 'relative' : 'fixed')) {
                        return
                    }
                    if (mode === 'fixed') {
                        setIncludeTime(true)
                    }
                    updateVariable({
                        ...variable,
                        default_value: mode === 'relative' ? '-0d' : dayjs().format(DATE_TIME_FORMAT),
                    })
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
                            aria-label="Amount"
                            className="w-24"
                            value={relativeValue.amount}
                            onChange={(event) =>
                                updateVariable({
                                    ...variable,
                                    default_value: `-${normalizeRelativeDateAmount(event.target.value)}${relativeValue.unit}`,
                                })
                            }
                        />
                        <Select<RelativeDateUnit>
                            items={RELATIVE_DATE_UNITS}
                            value={relativeValue.unit}
                            onValueChange={(unit) =>
                                updateVariable({
                                    ...variable,
                                    default_value: `-${relativeValue.amount}${unit ?? 'd'}`,
                                })
                            }
                        >
                            <SelectTrigger id={unitId} aria-label="Unit" className="grow">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                {RELATIVE_DATE_UNITS.map((unit) => (
                                    <SelectItem key={unit.value} value={unit.value}>
                                        {unit.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Text size="xs" variant="muted" render={<span />} className="whitespace-nowrap">
                            ago
                        </Text>
                    </div>
                    <Text size="xs" variant="muted" render={<span />}>
                        <span>Current value:&nbsp;</span>
                        <span translate="no">{formatRelativeDateValue(defaultValue)}</span>
                    </Text>
                </>
            ) : (
                <DatePicker
                    className="w-fit rounded-md border border-border"
                    value={fixedDate.isValid() ? fixedDate.toDate() : new Date()}
                    // Variables often point at a future date, and the picker caps at today without a maximum.
                    maxDate={dayjs().add(10, 'year').toDate()}
                    showTime={includeTime}
                    showTimeToggle
                    onIncludeTimeChange={setIncludeTime}
                    onApply={(date) =>
                        updateVariable({
                            ...variable,
                            default_value: dayjs(date).format(includeTime ? DATE_TIME_FORMAT : DATE_FORMAT),
                        })
                    }
                />
            )}
        </div>
    )
}
