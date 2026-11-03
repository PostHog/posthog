import { useActions } from 'kea'

import { DropdownMenuCheckboxItem, MenuEmpty } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'

import { filterValues } from './filterBarFields'
import { filterBarLogic } from './filterBarLogic'
import { FilterBarTypedValueItem } from './FilterBarTypedValueItem'
import { FilterBarItem } from './filterBarTypes'

const DATE_FORMAT = 'YYYY-MM-DD'

const DATE_PRESETS: { label: string; value: () => string }[] = [
    { label: 'Today', value: () => dayjs().format(DATE_FORMAT) },
    { label: 'Yesterday', value: () => dayjs().subtract(1, 'day').format(DATE_FORMAT) },
    { label: '7 days ago', value: () => dayjs().subtract(7, 'day').format(DATE_FORMAT) },
    { label: '30 days ago', value: () => dayjs().subtract(30, 'day').format(DATE_FORMAT) },
    { label: 'Start of this month', value: () => dayjs().startOf('month').format(DATE_FORMAT) },
    { label: 'Start of this year', value: () => dayjs().startOf('year').format(DATE_FORMAT) },
]

/** One date: a preset, or a date typed as YYYY-MM-DD in the search field. */
export function FilterBarDateValueItems({ item, query }: { item: FilterBarItem; query: string }): JSX.Element {
    const { setItemValue } = useActions(filterBarLogic)
    const selected = filterValues(item.filter).map(String)
    const typed = query.trim()
    const typedIsDate = dayjs(typed, DATE_FORMAT, true).isValid()

    return (
        <>
            {typed && !typedIsDate && <MenuEmpty>Type a date as YYYY-MM-DD</MenuEmpty>}
            {typed && typedIsDate && (
                <FilterBarTypedValueItem
                    label={`Use ${typed}`}
                    keepOpen={false}
                    onPick={() => setItemValue(item.id, typed)}
                />
            )}
            {DATE_PRESETS.map((preset) => {
                const value = preset.value()
                return (
                    <DropdownMenuCheckboxItem
                        key={preset.label}
                        checked={selected.includes(value)}
                        closeOnClick
                        onCheckedChange={() => setItemValue(item.id, value)}
                        data-attr="filter-bar-value"
                    >
                        {preset.label}
                        <span className="ms-auto text-muted-foreground">{value}</span>
                    </DropdownMenuCheckboxItem>
                )
            })}
        </>
    )
}
