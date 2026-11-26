import { useMemo, useState } from 'react'

import { Combobox, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { type OptionsLoader, useSearchedOptions } from './useSearchedOptions'

export type ValueOption = {
    value: string
    count?: number
}

export type ValueListProps = {
    /** Left out, the person types each value. */
    load?: OptionsLoader<ValueOption>
    selected: string[]
    onChange: (selected: string[]) => void
}

function emptyText(hasLoader: boolean, loading: boolean, failed: boolean): string {
    if (!hasLoader) {
        return 'Type a value'
    }
    if (failed) {
        return "Couldn't load values"
    }
    if (loading) {
        return 'Loading…'
    }
    return 'No values seen recently'
}

export function ValueList({ load, selected, onChange }: ValueListProps): JSX.Element {
    const [search, setSearch] = useState('')
    const { options, loading, failed } = useSearchedOptions(load, search)

    const counts = useMemo(() => new Map(options.map((option) => [option.value, option.count])), [options])
    const total = options.reduce((sum, option) => sum + (option.count ?? 0), 0)
    const typed = search.trim()
    // Picked values stay listed after a search moves on, so they can be unticked.
    const items = [...new Set([...(typed ? [typed] : []), ...selected, ...options.map((option) => option.value)])]

    return (
        <Combobox
            inline
            multiple
            items={items}
            value={selected}
            onValueChange={(next: string[]) => onChange(next)}
            inputValue={search}
            onInputValueChange={setSearch}
            filter={null}
        >
            <ComboboxInput placeholder={load ? 'Search values' : 'Type a value'} showTrigger={false} autoFocus />
            <ComboboxEmpty>{emptyText(!!load, loading, failed)}</ComboboxEmpty>
            <ComboboxList className="max-h-64">
                {(value: string) => {
                    const count = counts.get(value)
                    return (
                        // quill reserves the check mark's gutter only inside a popup, so an inline list adds it here.
                        <ComboboxItem key={value} value={value} className="ps-7" data-attr="dashboard-v2-filter-value">
                            <span className="min-w-0 flex-1 truncate">{value}</span>
                            {count !== undefined && total > 0 && (
                                <span className="text-xs tabular-nums text-muted-foreground">
                                    {humanFriendlyNumber(count)} · {Math.round((count / total) * 100)}%
                                </span>
                            )}
                        </ComboboxItem>
                    )
                }}
            </ComboboxList>
        </Combobox>
    )
}
