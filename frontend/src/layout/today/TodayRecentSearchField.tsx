import { useActions, useValues } from 'kea'
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

import { todaySpacesLogic } from './todaySpacesLogic'

export function TodayRecentSearchField(): JSX.Element {
    const { recentQuery, recentItems } = useValues(todaySpacesLogic)
    const { setRecentQuery, setRecentSearchOpen } = useActions(todaySpacesLogic)
    const hasQuery = recentQuery !== ''
    const label = hasQuery ? 'Clear search' : 'Close search'
    const clearOrClose = (): void => (hasQuery ? setRecentQuery('') : setRecentSearchOpen(false))

    return (
        <InputGroup className="min-w-0 flex-1">
            <InputGroupInput
                autoFocus
                value={recentQuery}
                placeholder="Search recent…"
                aria-label="Search recent"
                data-attr="today-recent-search"
                onChange={(event: ChangeEvent<HTMLInputElement>) => setRecentQuery(event.target.value)}
                onKeyDown={(event: KeyboardEvent<HTMLInputElement>) => {
                    if (event.key === 'Escape') {
                        event.preventDefault()
                        event.stopPropagation()
                        clearOrClose()
                    }
                }}
                onBlur={() => !hasQuery && setRecentSearchOpen(false)}
            />
            <InputGroupAddon align="inline-end">
                {hasQuery && (
                    <InputGroupText className="tabular-nums">
                        {recentItems.length === 0 ? 'No results' : recentItems.length}
                    </InputGroupText>
                )}
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <InputGroupButton
                                size="icon-xs"
                                aria-label={label}
                                // Keeps focus in the field, so blur doesn't close it before the click lands.
                                onMouseDown={(event: MouseEvent) => event.preventDefault()}
                                onClick={clearOrClose}
                                data-attr="today-recent-search-clear"
                            />
                        }
                    >
                        <IconX />
                    </TooltipTrigger>
                    <TooltipContent>{label}</TooltipContent>
                </Tooltip>
            </InputGroupAddon>
        </InputGroup>
    )
}
