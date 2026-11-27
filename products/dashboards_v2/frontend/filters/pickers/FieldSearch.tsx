import { useState } from 'react'

import {
    Autocomplete,
    AutocompleteInput,
    AutocompleteItem,
    AutocompleteList,
    AutocompleteStatus,
    Button,
} from '@posthog/quill'

import { type OptionsLoader, useSearchedOptions } from './useSearchedOptions'

export type FieldOption = {
    key: string
    label: string
}

export type FieldSearchProps<Option extends FieldOption> = {
    load: OptionsLoader<Option>
    onPick: (option: Option) => void
    placeholder?: string
}

function statusText(loading: boolean, count: number): string | null {
    if (loading) {
        return 'Loading…'
    }
    return count === 0 ? 'Nothing matches' : null
}

export function FieldSearch<Option extends FieldOption>({
    load,
    onPick,
    placeholder = 'Search fields',
}: FieldSearchProps<Option>): JSX.Element {
    const [search, setSearch] = useState('')
    const { options, loading, failed, retry } = useSearchedOptions(load, search)
    const [highlighted, setHighlighted] = useState<Option | undefined>()

    return (
        <div className="w-80">
            <Autocomplete
                inline
                mode="none"
                items={options}
                value={search}
                onValueChange={setSearch}
                itemToStringValue={(option: Option) => option.label}
                onItemHighlighted={(option: Option | undefined) => setHighlighted(option)}
            >
                <AutocompleteInput
                    placeholder={placeholder}
                    autoFocus
                    onKeyDown={(event) => {
                        // Enter with nothing highlighted takes the top match, as typing a name then Enter expects.
                        const option = highlighted ?? options[0]
                        if (event.key === 'Enter' && option) {
                            event.preventDefault()
                            onPick(option)
                        }
                    }}
                />
                {failed ? (
                    <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-sm text-secondary">
                        Couldn't load fields.
                        <Button size="sm" variant="outline" onClick={retry} data-attr="dashboard-v2-field-search-retry">
                            Try again
                        </Button>
                    </div>
                ) : (
                    <AutocompleteStatus>{(count) => statusText(loading, count)}</AutocompleteStatus>
                )}
                <AutocompleteList className="max-h-72">
                    {(option: Option) => (
                        <AutocompleteItem
                            key={option.key}
                            value={option}
                            onClick={() => onPick(option)}
                            data-attr="dashboard-v2-field-option"
                        >
                            <span className="truncate">{option.label}</span>
                            {option.label !== option.key && (
                                <span className="ml-auto truncate font-mono text-xs text-muted-foreground">
                                    {option.key}
                                </span>
                            )}
                        </AutocompleteItem>
                    )}
                </AutocompleteList>
            </Autocomplete>
        </div>
    )
}
