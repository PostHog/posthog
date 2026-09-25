import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSnack, Popover } from '@posthog/lemon-ui'

import { FacetDefinition, FacetFilter, FacetSearchValue, MatchesText, findFacet, formatFacetValue } from './facetQuery'
import { facetSearchBarLogic } from './facetSearchBarLogic'

export interface FacetSearchBarProps<TItem> {
    facets: FacetDefinition<TItem>[]
    /** Loaded items. Suggestions and their counts come from these; the bar never fetches. */
    items: TItem[]
    value: FacetSearchValue
    onChange: (value: FacetSearchValue) => void
    matchesText: MatchesText<TItem>
    /** Shown while no pill is set. */
    placeholder: string
    /** Keys the bar's state and marks the input for autocapture. */
    dataAttr: string
}

function pillLabel<TItem>(facets: FacetDefinition<TItem>[], filter: FacetFilter): string {
    const facet = findFacet(facets, filter.facet)
    return `${facet?.label ?? filter.facet}${filter.negated ? ' is not' : ''}: ${formatFacetValue(facet, filter.value)}`
}

export function FacetSearchBar<TItem>({
    facets,
    items,
    value,
    onChange,
    matchesText,
    placeholder,
    dataAttr,
}: FacetSearchBarProps<TItem>): JSX.Element {
    const logic = facetSearchBarLogic({ id: dataAttr, facets, items, value, onChange, matchesText })
    const { input, open, suggestions, highlightedIndex, tabTarget, title, hints } = useValues(logic)
    const {
        setInput,
        setOpen,
        moveHighlight,
        applySuggestion,
        applyHighlighted,
        applyTabTarget,
        removeFilter,
        removeLastFilter,
    } = useActions(logic)

    const listboxId = `${dataAttr}-listbox`
    const optionId = (index: number): string => `${listboxId}-option-${index}`
    const activeOptionId = open && suggestions.length ? optionId(highlightedIndex) : undefined

    useEffect(() => {
        if (activeOptionId) {
            document.getElementById(activeOptionId)?.scrollIntoView?.({ block: 'nearest' })
        }
    }, [activeOptionId])

    const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        const caretAtEnd =
            event.currentTarget.selectionStart === input.length && event.currentTarget.selectionEnd === input.length
        if (event.key === 'ArrowDown') {
            event.preventDefault()
            if (open) {
                moveHighlight(1)
            } else {
                setOpen(true)
            }
        } else if (event.key === 'ArrowUp') {
            event.preventDefault()
            moveHighlight(-1)
        } else if (event.key === 'Enter') {
            event.preventDefault()
            if (open) {
                applyHighlighted()
            }
        } else if ((event.key === 'Tab' || (event.key === 'ArrowRight' && caretAtEnd)) && open && tabTarget) {
            event.preventDefault()
            applyTabTarget()
        } else if (event.key === 'Escape') {
            setOpen(false)
        } else if (event.key === 'Backspace' && input === '' && value.filters.length > 0) {
            event.preventDefault()
            removeLastFilter()
        }
    }

    const overlay = open ? (
        <div className="w-96 max-w-full">
            <div className="px-2 py-1 text-xs font-semibold text-secondary">{title}</div>
            <div role="listbox" id={listboxId} aria-label={title} className="max-h-96 overflow-y-auto">
                {suggestions.map((suggestion, index) => (
                    <LemonButton
                        key={suggestion.id}
                        id={optionId(index)}
                        role="option"
                        aria-selected={index === highlightedIndex}
                        active={index === highlightedIndex}
                        tabIndex={-1}
                        fullWidth
                        size="small"
                        // Keeps focus in the input, so the combobox stays the one focused element.
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => applySuggestion(suggestion)}
                    >
                        <span className="flex items-center gap-2 w-full min-w-0">
                            <span
                                className={clsx(
                                    'shrink-0',
                                    suggestion.kind === 'facet' && 'font-mono',
                                    suggestion.kind === 'none' && 'text-secondary font-normal'
                                )}
                            >
                                {suggestion.label}
                            </span>
                            {suggestion.detail && (
                                <span className="text-secondary font-normal truncate">{suggestion.detail}</span>
                            )}
                            {suggestion.count !== undefined && (
                                <span className="ml-auto text-secondary font-normal tabular-nums" translate="no">
                                    {suggestion.count}
                                </span>
                            )}
                        </span>
                    </LemonButton>
                ))}
            </div>
            <div
                data-attr="facet-search-bar-hints"
                className="flex flex-wrap gap-x-3 px-2 pt-1 mt-1 border-t text-xs text-secondary"
            >
                {hints.map((hint) => (
                    <span key={hint}>{hint}</span>
                ))}
            </div>
        </div>
    ) : null

    return (
        <Popover visible={open} overlay={overlay} placement="bottom-start" onClickOutside={() => setOpen(false)}>
            <div className="@container w-full min-w-0">
                <LemonInput
                    type="text"
                    fullWidth
                    data-attr={dataAttr}
                    role="combobox"
                    aria-label={placeholder}
                    aria-autocomplete="list"
                    aria-expanded={open}
                    aria-controls={open ? listboxId : undefined}
                    aria-activedescendant={activeOptionId}
                    className="h-auto min-h-10 flex-wrap gap-y-1 py-1 [&_.LemonInput__input]:min-w-40"
                    value={input}
                    placeholder={value.filters.length ? 'Add a filter or search' : placeholder}
                    onChange={setInput}
                    onKeyDown={onKeyDown}
                    onFocus={() => setOpen(true)}
                    onBlur={() => setOpen(false)}
                    prefix={
                        <>
                            <IconSearch className="text-secondary shrink-0" />
                            {value.filters.map((filter) => {
                                const label = pillLabel(facets, filter)
                                return (
                                    <LemonSnack
                                        key={`${filter.negated ? '-' : ''}${filter.facet}:${filter.value}`}
                                        closeLabel={`Remove filter ${label}`}
                                        onClose={() => removeFilter(filter)}
                                        className="max-w-80"
                                    >
                                        <span className={filter.negated ? 'text-danger' : undefined}>{label}</span>
                                    </LemonSnack>
                                )
                            })}
                        </>
                    }
                />
            </div>
        </Popover>
    )
}
