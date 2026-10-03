import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSnack, Popover, PopoverReferenceContext } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'

import { ClientFacet, FacetSearchRows, FacetSearchValue, ServerFacet, facetFilterKey } from './facetSearch'
import { facetSearchBarLogic } from './facetSearchBarLogic'
import { isPillLabelMissing, pillLabel } from './facetSuggestions'

const MISSING_LABEL_NOTE = " (couldn't load the label)"

interface FacetSearchBarBaseProps {
    value: FacetSearchValue
    onChange: (value: FacetSearchValue) => void
    /** Shown while no pill is set. */
    placeholder: string
    /** Keys the bar's state and marks the input for autocapture. Two bars mounted at once need different values. */
    dataAttr: string
}

export interface ClientFacetSearchBarProps<TRow> extends FacetSearchBarBaseProps {
    facets: ClientFacet<TRow>[]
    /** The rows the browser holds. Suggestions and their counts come from these. */
    data: FacetSearchRows<TRow>
}

export interface ServerFacetSearchBarProps extends FacetSearchBarBaseProps {
    facets: ServerFacet[]
    data?: never
}

export type FacetSearchBarProps<TRow> = ClientFacetSearchBarProps<TRow> | ServerFacetSearchBarProps

/**
 * A search input that turns `facet:value` into removable pills, with suggestions, counts and keyboard support.
 * Pass rows as `data` to filter in the browser with `filterFacetRows`, or leave `data` out and send
 * `toFacetQuery(value)` to an API. See README.md next to this file.
 */
export function FacetSearchBar<TRow>({
    facets,
    data,
    value,
    onChange,
    placeholder,
    dataAttr,
}: FacetSearchBarProps<TRow>): JSX.Element {
    const logic = facetSearchBarLogic({ id: dataAttr, facets, data: data ?? null, value, onChange })
    const {
        input,
        open,
        options,
        statusMessage,
        highlightedIndex,
        highlightedSuggestion,
        tabTarget,
        title,
        hints,
        valueLabels,
        failedLabelFacets,
    } = useValues(logic)
    const {
        setInput,
        setOpen,
        moveHighlight,
        setHighlightedIndex,
        applySuggestion,
        applyHighlighted,
        applyTabTarget,
        removeFilter,
        removeLastFilter,
    } = useActions(logic)

    const inputRef = useRef<HTMLInputElement>(null)
    const movedByKeyboard = useRef(false)
    const listboxId = `${dataAttr}-listbox`
    const optionId = (index: number): string => `${listboxId}-option-${index}`
    const expanded = open && (options.length > 0 || !!statusMessage)
    const activeOptionId = expanded && highlightedSuggestion ? optionId(highlightedIndex) : undefined

    // Scrolling for the pointer would move the list under it and change the row it points at.
    useEffect(() => {
        if (activeOptionId && movedByKeyboard.current) {
            document.getElementById(activeOptionId)?.scrollIntoView?.({ block: 'nearest' })
        }
        movedByKeyboard.current = false
    }, [activeOptionId])

    const moveHighlightByKeyboard = (delta: number): void => {
        movedByKeyboard.current = true
        moveHighlight(delta)
    }

    const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        // Keys during IME composition belong to the input method, not to the suggestions.
        // Safari sends the Enter that confirms the text after composition ends, marked only by keyCode 229.
        if (event.nativeEvent.isComposing || event.keyCode === 229) {
            return
        }
        const caretAtEnd =
            event.currentTarget.selectionStart === input.length && event.currentTarget.selectionEnd === input.length
        if (event.key === 'ArrowDown') {
            event.preventDefault()
            if (open) {
                moveHighlightByKeyboard(1)
            } else {
                setOpen(true)
            }
        } else if (event.key === 'ArrowUp' && expanded) {
            event.preventDefault()
            moveHighlightByKeyboard(-1)
        } else if (event.key === 'Enter' && expanded) {
            event.preventDefault()
            applyHighlighted()
        } else if (
            ((event.key === 'Tab' && !event.shiftKey) || (event.key === 'ArrowRight' && caretAtEnd)) &&
            open &&
            tabTarget
        ) {
            event.preventDefault()
            applyTabTarget()
        } else if (event.key === 'Escape' && expanded) {
            event.stopPropagation()
            setOpen(false)
        } else if (event.key === 'Backspace' && input === '' && value.filters.length > 0) {
            event.preventDefault()
            removeLastFilter()
        }
    }

    const overlay = expanded ? (
        // Pressing anywhere in the popover (scrollbar, title, hint row) keeps the focus, and so the popover, in the input.
        <div className="w-96 max-w-full" onMouseDown={(event) => event.preventDefault()}>
            <div className="px-2 py-1 text-xs font-semibold text-secondary">{title}</div>
            {options.length > 0 && (
                <div role="listbox" id={listboxId} aria-label={title} className="max-h-96 overflow-y-auto">
                    {options.map((suggestion, index) => (
                        <LemonButton
                            key={suggestion.id}
                            id={optionId(index)}
                            data-attr={`${dataAttr}-suggestion`}
                            role="option"
                            aria-selected={index === highlightedIndex}
                            active={index === highlightedIndex}
                            tabIndex={-1}
                            fullWidth
                            size="small"
                            onClick={() => applySuggestion(suggestion)}
                            onMouseEnter={() => {
                                movedByKeyboard.current = false
                                setHighlightedIndex(index)
                            }}
                        >
                            <span className="flex items-center gap-2 w-full min-w-0">
                                <span
                                    className={suggestion.kind === 'facet' ? 'shrink-0 font-mono' : 'truncate'}
                                    title={suggestion.kind === 'facet' ? undefined : suggestion.label}
                                >
                                    {suggestion.label}
                                </span>
                                {suggestion.detail && (
                                    <span className="text-secondary font-normal truncate">{suggestion.detail}</span>
                                )}
                                {suggestion.count !== undefined && (
                                    <span
                                        className="ml-auto shrink-0 text-secondary font-normal tabular-nums"
                                        translate="no"
                                    >
                                        {suggestion.count}
                                    </span>
                                )}
                            </span>
                        </LemonButton>
                    ))}
                </div>
            )}
            {statusMessage && (
                <div aria-hidden className="px-2 py-1 text-secondary">
                    {statusMessage}
                </div>
            )}
            <div
                data-attr={`${dataAttr}-hints`}
                className="flex flex-wrap gap-x-3 px-2 pt-1 mt-1 border-t text-xs text-secondary"
            >
                {hints.map(({ keys, action }) => (
                    <span key={keys.join('+')} className="flex items-center gap-x-1">
                        {keys.map((key) => (
                            <KeyboardShortcut key={key} {...{ [key]: true }} />
                        ))}
                        <span>{action}</span>
                    </span>
                ))}
            </div>
        </div>
    ) : null

    return (
        // The input's blur is the one close path: pressing outside moves the focus away.
        <Popover visible={expanded} overlay={overlay} placement="bottom-start">
            {/* Pressing the bar around the text keeps the focus, and so the popover and its Tab target, in the input. */}
            <div
                className="w-full min-w-0"
                onMouseDown={(event) => event.target !== inputRef.current && event.preventDefault()}
            >
                <div role="status" aria-live="polite" className="sr-only">
                    {expanded ? statusMessage : null}
                </div>
                <LemonInput
                    type="text"
                    fullWidth
                    data-attr={dataAttr}
                    role="combobox"
                    aria-label={placeholder}
                    aria-autocomplete="list"
                    aria-expanded={expanded && options.length > 0}
                    aria-controls={expanded && options.length > 0 ? listboxId : undefined}
                    aria-activedescendant={activeOptionId}
                    className="h-auto min-h-10 flex-wrap gap-y-1 py-1 [&_input]:min-w-40"
                    value={input}
                    placeholder={value.filters.length ? 'Add a filter or search' : placeholder}
                    onChange={setInput}
                    onKeyDown={onKeyDown}
                    inputRef={inputRef}
                    onFocus={() => setOpen(true)}
                    onClick={() => !open && setOpen(true)}
                    onBlur={() => setOpen(false)}
                    prefix={
                        <>
                            <IconSearch className="text-secondary shrink-0" />
                            {/* Pills are not the popover's trigger, so their close buttons must not look pressed while it is open. */}
                            <PopoverReferenceContext.Provider value={null}>
                                {value.filters.map((filter) => {
                                    const label = pillLabel(filter, facets, valueLabels)
                                    const labelFailed = isPillLabelMissing(filter, failedLabelFacets, valueLabels)
                                    return (
                                        <LemonSnack
                                            key={facetFilterKey(filter)}
                                            data-attr={`${dataAttr}-filter`}
                                            title={labelFailed ? `${label}${MISSING_LABEL_NOTE}` : label}
                                            closeLabel={`Remove filter ${label}`}
                                            onClose={() => {
                                                removeFilter(filter)
                                                inputRef.current?.focus()
                                            }}
                                            className="max-w-80"
                                        >
                                            <span className={filter.negated ? 'text-danger' : undefined}>{label}</span>
                                            {labelFailed && <span className="sr-only">{MISSING_LABEL_NOTE}</span>}
                                        </LemonSnack>
                                    )
                                })}
                            </PopoverReferenceContext.Provider>
                        </>
                    }
                />
            </div>
        </Popover>
    )
}
