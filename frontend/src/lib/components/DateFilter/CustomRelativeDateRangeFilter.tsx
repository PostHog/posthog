import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonSelectOptionLeaf } from '@posthog/lemon-ui'

import { DateOption } from './rollingDateRangeFilterLogic'

const dateOptions: LemonSelectOptionLeaf<DateOption>[] = [
    { value: 'seconds', label: 'seconds' },
    { value: 'minutes', label: 'minutes' },
    { value: 'hours', label: 'hours' },
    { value: 'days', label: 'days' },
    { value: 'weeks', label: 'weeks' },
    { value: 'months', label: 'months' },
    { value: 'quarters', label: 'quarters' },
    { value: 'years', label: 'years' },
]

const dateOptionToCode: Record<DateOption, string> = {
    years: 'y',
    quarters: 'q',
    months: 'm',
    weeks: 'w',
    days: 'd',
    hours: 'h',
    minutes: 'M',
    seconds: 's',
}

function parseRelativeDate(value: string | null | undefined): { counter: number; option: DateOption } {
    if (!value || typeof value !== 'string') {
        return { counter: 7, option: 'days' }
    }
    const optionsMap: Record<string, DateOption> = {
        y: 'years',
        q: 'quarters',
        m: 'months',
        w: 'weeks',
        d: 'days',
        h: 'hours',
        M: 'minutes',
        s: 'seconds',
    }
    const lastChar = value.slice(-1)
    const option = optionsMap[lastChar]
    const counter = parseInt(value.slice(1, -1))
    if (option && counter) {
        return { counter, option }
    }
    return { counter: 7, option: 'days' }
}

type CustomRelativeDateRangeFilterProps = {
    dateFrom?: string | null
    dateTo?: string | null
    onChange: (dateFrom: string, dateTo: string) => void
    onBack: () => void
}

export function CustomRelativeDateRangeFilter({
    dateFrom,
    dateTo,
    onChange,
    onBack,
}: CustomRelativeDateRangeFilterProps): JSX.Element {
    const parsedFrom = parseRelativeDate(dateFrom)
    const parsedTo = parseRelativeDate(dateTo)

    const [fromCounter, setFromCounter] = useState<number | null>(parsedFrom.counter)
    const [fromOption, setFromOption] = useState<DateOption>(parsedFrom.option)
    const [toCounter, setToCounter] = useState<number | null>(parsedTo.counter > 0 ? parsedTo.counter : 1)
    const [toOption, setToOption] = useState<DateOption>(parsedTo.option)

    const fromValue = fromCounter ? `-${fromCounter}${dateOptionToCode[fromOption]}` : null
    const toValue = toCounter ? `-${toCounter}${dateOptionToCode[toOption]}` : null

    const isValid = fromValue && toValue && fromCounter && toCounter && fromCounter > 0 && toCounter > 0

    return (
        <div className="space-y-2 p-2" style={{ width: 300 }}>
            <div>
                <LemonButton size="xsmall" type="tertiary" onClick={onBack}>
                    &larr; Back
                </LemonButton>
            </div>
            <div className="font-semibold text-sm">Custom relative date range</div>
            <div className="space-y-1">
                <div className="text-xs text-muted">From</div>
                <div className="flex items-center gap-1">
                    <LemonInput
                        type="number"
                        value={fromCounter ?? 0}
                        min={1}
                        onChange={(value) => setFromCounter(value ? Math.round(value) : null)}
                        size="small"
                        className="w-20"
                    />
                    <LemonSelect
                        value={fromOption}
                        onChange={setFromOption}
                        options={dateOptions}
                        size="small"
                        className="min-w-24"
                    />
                    <span className="text-xs text-muted whitespace-nowrap">ago</span>
                </div>
            </div>
            <div className="space-y-1">
                <div className="text-xs text-muted">To</div>
                <div className="flex items-center gap-1">
                    <LemonInput
                        type="number"
                        value={toCounter ?? 0}
                        min={1}
                        onChange={(value) => setToCounter(value ? Math.round(value) : null)}
                        size="small"
                        className="w-20"
                    />
                    <LemonSelect
                        value={toOption}
                        onChange={setToOption}
                        options={dateOptions}
                        size="small"
                        className="min-w-24"
                    />
                    <span className="text-xs text-muted whitespace-nowrap">ago</span>
                </div>
            </div>
            <LemonDivider />
            <LemonButton
                type="primary"
                fullWidth
                center
                disabled={!isValid}
                onClick={() => {
                    if (fromValue && toValue) {
                        onChange(fromValue, toValue)
                    }
                }}
            >
                Apply
            </LemonButton>
        </div>
    )
}
