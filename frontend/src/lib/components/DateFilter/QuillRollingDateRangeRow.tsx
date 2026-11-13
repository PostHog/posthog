import { useActions, useValues } from 'kea'

import { DropdownMenuRadioItem } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { RelativeRangeInput, type RelativeRangeUnit } from './RelativeRangeInput'
import { rollingDateRangeFilterLogic } from './rollingDateRangeFilterLogic'

// A menu treats typed keys as item navigation, which would steal them from the count input
function keepKeysInField(event: React.KeyboardEvent): void {
    if (event.key !== 'Escape') {
        event.stopPropagation()
    }
}

export interface QuillRollingDateRangeRowProps {
    pageKey: string
    value: string
    dateFrom?: string | null | dayjs.Dayjs
    selected: boolean
    max?: number | null
    units: RelativeRangeUnit[]
    onChange: (fromDate: string) => void
    makeLabel?: (key: React.ReactNode, startOfRange?: React.ReactNode) => React.ReactNode
}

export function QuillRollingDateRangeRow({
    pageKey,
    value,
    dateFrom,
    selected,
    max,
    units,
    onChange,
    makeLabel,
}: QuillRollingDateRangeRowProps): JSX.Element {
    const logic = rollingDateRangeFilterLogic({ pageKey, dateFrom, max, inUse: selected, onChange })
    const { counter, dateOption, formattedDate, startOfDateRange } = useValues(logic)
    const { setCounter, setDateOption, select } = useActions(logic)

    return (
        <div className="flex items-center gap-1">
            <DropdownMenuRadioItem
                value={value}
                className="w-auto shrink-0"
                data-attr="rolling-date-range-filter"
                onClick={select}
                tooltip={makeLabel?.(formattedDate, startOfDateRange)}
            >
                In the last
            </DropdownMenuRadioItem>
            <div onKeyDown={keepKeysInField}>
                <RelativeRangeInput
                    value={{ count: counter ?? 1, unit: dateOption as RelativeRangeUnit }}
                    onChange={({ count, unit }) => {
                        if (unit !== dateOption) {
                            setDateOption(unit)
                        } else {
                            setCounter(count)
                        }
                    }}
                    units={units}
                    max={max ?? undefined}
                />
            </div>
        </div>
    )
}
