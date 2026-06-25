import { useMemo, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover/Popover'

export interface InputWithSuggestionsDropdownProps {
    /** Current value of the input. Free text — user can type anything, suggestions are only hints. */
    value: string
    onChange: (next: string) => void
    placeholder?: string
    'data-attr'?: string
    /** Suggestions to surface in the popover. Each value is shown verbatim and copied into `value` on click. */
    suggestions: string[]
    suggestionsLoading?: boolean
    /** Search input placeholder inside the popover. */
    searchPlaceholder?: string
    /** Text shown when `suggestions` is empty after loading. */
    emptyMessage?: string
    /** Text shown when the search term filters out every suggestion. Receives the current term. */
    noMatchMessage?: (term: string) => string
    /** Text shown next to the spinner while suggestions load. */
    loadingMessage?: string
}

/**
 * A free-text input that opens a searchable popover of suggestions on focus.
 *
 * The popover's search input is independent from the main input — typing in the
 * search filters the suggestions list without touching `value`, so the user can
 * use suggestions as a shortcut without losing the value they typed. Clicking a
 * suggestion overwrites `value` and closes the popover.
 *
 * Stateless / presentation only — bring your own data source (e.g. an integration's
 * available resources).
 */
export function InputWithSuggestionsDropdown({
    value,
    onChange,
    placeholder,
    'data-attr': dataAttr,
    suggestions,
    suggestionsLoading = false,
    searchPlaceholder = 'Filter suggestions…',
    emptyMessage = 'No suggestions available.',
    noMatchMessage = (term) => `No suggestions match "${term}".`,
    loadingMessage = 'Loading…',
}: InputWithSuggestionsDropdownProps): JSX.Element {
    const [open, setOpen] = useState(false)
    const [searchTerm, setSearchTerm] = useState('')

    const filtered = useMemo(() => {
        const needle = searchTerm.trim().toLowerCase()
        if (!needle) {
            return suggestions
        }
        return suggestions.filter((suggestion) => suggestion.toLowerCase().includes(needle))
    }, [suggestions, searchTerm])

    return (
        <Popover
            visible={open}
            onClickOutside={() => {
                setSearchTerm('')
                setOpen(false)
            }}
            placement="bottom-start"
            matchWidth
            overlay={
                <div className="flex flex-col gap-2 p-2 min-w-80">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder={searchPlaceholder}
                        value={searchTerm}
                        onChange={setSearchTerm}
                    />
                    {suggestionsLoading ? (
                        <p className="m-0 px-2 py-1 text-xs text-secondary flex items-center gap-1">
                            <Spinner /> {loadingMessage}
                        </p>
                    ) : suggestions.length === 0 ? (
                        <p className="m-0 px-2 py-1 text-xs text-secondary">{emptyMessage}</p>
                    ) : filtered.length === 0 ? (
                        <p className="m-0 px-2 py-1 text-xs text-secondary">{noMatchMessage(searchTerm)}</p>
                    ) : (
                        <div className="flex flex-col max-h-64 overflow-y-auto">
                            {filtered.map((suggestion) => {
                                const isCurrent = suggestion === value
                                return (
                                    <LemonButton
                                        key={suggestion}
                                        size="small"
                                        fullWidth
                                        active={isCurrent}
                                        icon={isCurrent ? <IconCheck /> : undefined}
                                        onClick={() => {
                                            onChange(suggestion)
                                            setSearchTerm('')
                                            setOpen(false)
                                        }}
                                    >
                                        {suggestion}
                                    </LemonButton>
                                )
                            })}
                        </div>
                    )}
                </div>
            }
        >
            <LemonInput
                className="ph-ignore-input"
                data-attr={dataAttr}
                placeholder={placeholder}
                type="text"
                value={value}
                onChange={onChange}
                onFocus={() => setOpen(true)}
            />
        </Popover>
    )
}
