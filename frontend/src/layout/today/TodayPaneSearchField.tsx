import { ChangeEvent, KeyboardEvent, MouseEvent } from 'react'

import { IconX } from '@posthog/icons'
import {
    InputGroup,
    InputGroupAddon,
    InputGroupButton,
    InputGroupInput,
    InputGroupText,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

/** A pane section's search box. Escape or the button clears the query first, then closes the box. */
export function TodayPaneSearchField({
    query,
    resultCount,
    label,
    onQueryChange,
    onClose,
    dataAttr,
}: {
    query: string
    resultCount: number
    /** The accessible name, also the placeholder, for example "Search recent". */
    label: string
    onQueryChange: (query: string) => void
    onClose: () => void
    /** Prefix for the field's `data-attr` and its clear button's `-clear` one. */
    dataAttr: string
}): JSX.Element {
    const hasQuery = query !== ''
    const buttonLabel = hasQuery ? 'Clear search' : 'Close search'
    const clearOrClose = (): void => (hasQuery ? onQueryChange('') : onClose())

    return (
        <InputGroup className="min-w-0 flex-1">
            <InputGroupInput
                autoFocus
                value={query}
                placeholder={`${label}…`}
                aria-label={label}
                data-attr={dataAttr}
                onChange={(event: ChangeEvent<HTMLInputElement>) => onQueryChange(event.target.value)}
                onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Escape') {
                        event.preventDefault()
                        event.stopPropagation()
                        clearOrClose()
                    }
                }}
                onBlur={() => !hasQuery && onClose()}
            />
            <InputGroupAddon align="inline-end">
                {hasQuery && (
                    <InputGroupText className="tabular-nums">
                        {resultCount === 0 ? 'No results' : resultCount}
                    </InputGroupText>
                )}
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <InputGroupButton
                                size="icon-xs"
                                aria-label={buttonLabel}
                                // Keeps focus in the field, so blur doesn't close it before the click lands.
                                onMouseDown={(event: MouseEvent) => event.preventDefault()}
                                onClick={clearOrClose}
                                data-attr={`${dataAttr}-clear`}
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>{buttonLabel}</TooltipContent>
                </Tooltip>
            </InputGroupAddon>
        </InputGroup>
    )
}
