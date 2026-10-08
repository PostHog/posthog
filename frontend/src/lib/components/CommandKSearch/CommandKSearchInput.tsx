import { useActions, useValues } from 'kea'
import { useLayoutEffect, useRef } from 'react'

import { IconSearch, IconSparkles, IconX } from '@posthog/icons'
import { Button, InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput, cn } from '@posthog/quill'

import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { keyIntent } from './commandKKeys'
import { commandKSearchLogic } from './commandKSearchLogic'
import { rowDomId } from './CommandKSearchRow'

export const COMMAND_K_LISTBOX_ID = 'command-k-listbox'

export function CommandKSearchInput(): JSX.Element {
    const { text, cursor, chips, selectedChipIndex, highlightedRow, highlightIsFilterRow, tabAsksAi, isPaletteEmpty } =
        useValues(commandKSearchLogic)
    const { todayRailEnabled } = useValues(todayShellLogic)
    const { inputChanged, setCursor, applyKeyIntent, selectChip, clearQuery, askAi, closeCommand } =
        useActions(commandKSearchLogic)
    const inputRef = useRef<HTMLInputElement>(null)
    const pastingRef = useRef(false)

    // The logic moves the cursor when it commits or edits a chip, so mirror it onto the field.
    useLayoutEffect(() => {
        const input = inputRef.current
        if (input && document.activeElement === input && input.selectionStart !== cursor) {
            input.setSelectionRange(cursor, cursor)
        }
    }, [text, cursor])

    useLayoutEffect(() => {
        inputRef.current?.focus()
    }, [])

    const onKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
        // Keys confirm or move inside an IME composition, so leave them to the input. Safari reports 229.
        if (event.nativeEvent.isComposing || event.keyCode === 229) {
            return
        }
        const input = event.currentTarget
        const intent = keyIntent(event.key, event, {
            atStart: input.selectionStart === 0 && input.selectionEnd === 0,
            chipCount: chips.length,
            selectedChipIndex,
            tabHasAction: tabAsksAi || highlightIsFilterRow,
        })
        if (!intent) {
            return
        }
        event.preventDefault()
        if (intent.type === 'clear-or-close') {
            // Stop the dialog from closing, so the first press only clears the query.
            event.stopPropagation()
        }
        applyKeyIntent(intent)
    }

    return (
        <div className="flex items-center gap-1 p-2">
            {/* A fixed height, so committing a chip never resizes the field. Chips that overflow scroll sideways. */}
            <InputGroup className="flex-1">
                {/* The scroll container clips, so it gets room on the right for the selected chip's outline and gives it back with a negative margin. */}
                <InputGroupAddon
                    align="inline-start"
                    className="-mr-1 min-w-0 shrink overflow-x-auto pr-1 [scrollbar-width:none]"
                >
                    <IconSearch className="size-4 shrink-0" />
                    {chips.map((chip, index) => (
                        // Committed filters read as typed text: plain key, brand-tinted value.
                        <button
                            key={chip.key}
                            type="button"
                            tabIndex={-1}
                            data-attr="command-k-chip"
                            aria-label={`${chip.negated ? 'Not ' : ''}${chip.key}: ${chip.label}. Backspace removes it.`}
                            className={cn(
                                'flex max-w-60 shrink-0 items-center rounded-xs text-sm leading-none text-foreground',
                                selectedChipIndex === index && 'ring-2 ring-ring'
                            )}
                            onMouseDown={(event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault()}
                            onClick={() => selectChip(index)}
                        >
                            <span className="shrink-0">
                                {chip.negated ? '-' : ''}
                                {chip.key}:
                            </span>
                            <span className="truncate rounded-xs bg-[var(--primary)]/10 px-0.5 text-[var(--primary)]">
                                {chip.label}
                            </span>
                        </button>
                    ))}
                </InputGroupAddon>
                <InputGroupInput
                    ref={inputRef}
                    id="command-k-input"
                    data-attr="command-k-input"
                    role="combobox"
                    aria-expanded
                    aria-controls={COMMAND_K_LISTBOX_ID}
                    aria-autocomplete="list"
                    aria-activedescendant={highlightedRow ? rowDomId(highlightedRow.key) : undefined}
                    aria-label="Search"
                    autoComplete="off"
                    spellCheck={false}
                    placeholder={chips.length === 0 ? 'Search or ask PostHog AI… try is:dashboard' : undefined}
                    className="min-w-24 flex-1"
                    value={text}
                    onPaste={() => {
                        pastingRef.current = true
                    }}
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => {
                        const pasted = pastingRef.current
                        pastingRef.current = false
                        inputChanged(
                            event.target.value,
                            event.target.selectionStart ?? event.target.value.length,
                            pasted
                        )
                    }}
                    onSelect={(event: React.SyntheticEvent<HTMLInputElement>) => {
                        const nextCursor = event.currentTarget.selectionStart ?? 0
                        if (nextCursor !== cursor) {
                            setCursor(nextCursor)
                        }
                    }}
                    onKeyDown={onKeyDown}
                />
                <InputGroupAddon align="inline-end">
                    {tabAsksAi && (
                        <InputGroupButton
                            size="sm"
                            variant="secondary"
                            tabIndex={-1}
                            data-attr="command-k-ask-ai"
                            onMouseDown={(event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault()}
                            onClick={() => askAi()}
                        >
                            <IconSparkles />
                            Press Tab to ask AI
                        </InputGroupButton>
                    )}
                    {!isPaletteEmpty && (
                        <InputGroupButton
                            size="icon-xs"
                            tabIndex={-1}
                            aria-label="Clear search"
                            data-attr="command-k-clear"
                            className="mr-1"
                            onMouseDown={(event: React.MouseEvent<HTMLButtonElement>) => event.preventDefault()}
                            onClick={() => clearQuery()}
                        >
                            <IconX />
                        </InputGroupButton>
                    )}
                </InputGroupAddon>
            </InputGroup>
            {todayRailEnabled && (
                <Button
                    size="sm"
                    className="hidden shrink-0 max-md:flex"
                    data-attr="command-phone-cancel"
                    onClick={() => closeCommand()}
                >
                    Cancel
                </Button>
            )}
        </div>
    )
}
