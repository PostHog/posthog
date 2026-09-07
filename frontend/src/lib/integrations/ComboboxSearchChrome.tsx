import { type MouseEvent } from 'react'

import { IconRefresh } from '@posthog/icons'
import {
    Button,
    ComboboxInput,
    ComboboxListFooter,
    InputGroupAddon,
    InputGroupButton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

/** Keep the combobox from reading a control press as picking an item or as a dismiss. */
function swallowEvent(event: MouseEvent): void {
    event.preventDefault()
    event.stopPropagation()
}

export interface ComboboxSearchFieldProps {
    /** Plural noun for what's being searched, e.g. `branches`. Fills the placeholder and the refresh label. */
    itemsLabel: string
    loading: boolean
    disabled?: boolean
    onRefresh: () => void
}

/**
 * Search field for a combobox whose list is searched server-side. Refresh sits in the field's own addon
 * rather than beside it, which is what keeps the two the same height, and the field is inset to the
 * list's padding so it lines up with the items. The chevron is hidden because the popup is already open.
 */
export function ComboboxSearchField({
    itemsLabel,
    loading,
    disabled = false,
    onRefresh,
}: ComboboxSearchFieldProps): JSX.Element {
    return (
        <div className="p-1">
            <ComboboxInput placeholder={`Search ${itemsLabel}...`} showTrigger={false} className="w-full">
                <InputGroupAddon align="inline-end">
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <InputGroupButton
                                    size="icon-xs"
                                    disabled={disabled || loading}
                                    aria-label={`Refresh ${itemsLabel}`}
                                    onMouseDown={swallowEvent}
                                    onClick={(event: MouseEvent) => {
                                        swallowEvent(event)
                                        onRefresh()
                                    }}
                                >
                                    <IconRefresh className={loading ? 'animate-spin' : undefined} />
                                </InputGroupButton>
                            }
                        />
                        <TooltipContent>Refresh {itemsLabel}</TooltipContent>
                    </Tooltip>
                </InputGroupAddon>
            </ComboboxInput>
        </div>
    )
}

export interface ComboboxLoadMoreFooterProps {
    loadedCount: number
    /** Plural noun for the full list, e.g. `branches`. Reads as "matches" while a search is narrowing it. */
    itemsLabel: string
    searching: boolean
    loading: boolean
    onLoadMore: () => void
}

/** Paginated footer for a combobox list: how much of the list is loaded, and a way to get the next page. */
export function ComboboxLoadMoreFooter({
    loadedCount,
    itemsLabel,
    searching,
    loading,
    onLoadMore,
}: ComboboxLoadMoreFooterProps): JSX.Element {
    return (
        <ComboboxListFooter>
            <div className="px-2 pb-2">
                <div className="px-1 pb-2 text-center text-muted text-xs">
                    {`Showing ${loadedCount}+ ${searching ? 'matches' : itemsLabel}`}
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    className="w-full justify-center"
                    disabled={loading}
                    onMouseDown={swallowEvent}
                    onClick={(event: MouseEvent) => {
                        swallowEvent(event)
                        onLoadMore()
                    }}
                >
                    Load more
                </Button>
            </div>
        </ComboboxListFooter>
    )
}
