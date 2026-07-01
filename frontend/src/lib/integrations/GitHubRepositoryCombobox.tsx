import { useActions, useValues } from 'kea'
import { type MouseEvent, useRef, useState } from 'react'

import { IconGithub, IconRefresh } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxInput,
    ComboboxItem,
    ComboboxList,
    ComboboxListFooter,
    ComboboxTrigger,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { githubRepositorySearchLogic } from './githubRepositorySearchLogic'

export interface GitHubRepositoryComboboxProps {
    integrationId: number
    /** Selected repository in `owner/repo` format, or empty when nothing is picked. */
    value: string
    onChange: (value: string | null) => void
    disabled?: boolean
    placeholder?: string
    /** When true, prepends a "— No repository —" item so users can explicitly clear the selection. */
    showNoneOption?: boolean
}

/**
 * GitHub repository picker built on Quill's Combobox, mirroring the PostHog Code repo picker: a button
 * trigger, an in-popover search field driving server-side search, a paginated "Load more" footer, and a
 * refresh control. Searching and pagination are delegated to {@link githubRepositorySearchLogic} so large
 * accounts never load the full repository list up front.
 */
const NONE_SENTINEL = '\x00none'

export function GitHubRepositoryCombobox({
    integrationId,
    value,
    onChange,
    disabled = false,
    placeholder = 'Select repository...',
    showNoneOption = false,
}: GitHubRepositoryComboboxProps): JSX.Element {
    const logic = githubRepositorySearchLogic({ id: integrationId })
    const { repositoryNames, loading, hasMore, searchQuery, error } = useValues(logic)
    const { setSearchQuery, loadMore, refresh } = useActions(logic)

    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    const trimmedSearchQuery = searchQuery.trim()
    // While the popover is open we surface loading inline in the list; closed-and-loading shows a disabled
    // button so the trigger never flickers an empty selection.
    const showInlineLoadingState = open && loading
    // Distinguish "this account genuinely has no repos" from "the search/refresh just hasn't returned yet".
    const hasActiveSearchContext = open || trimmedSearchQuery.length > 0

    if (loading && !showInlineLoadingState && repositoryNames.length === 0) {
        return (
            <Button variant="outline" size="sm" disabled>
                <IconGithub className="shrink-0" />
                Loading repos...
            </Button>
        )
    }

    if (repositoryNames.length === 0 && !showInlineLoadingState && !hasActiveSearchContext && !error) {
        return (
            <Button variant="outline" size="sm" disabled>
                <IconGithub className="shrink-0" />
                No GitHub repos
            </Button>
        )
    }

    const items = showNoneOption ? [NONE_SENTINEL, ...repositoryNames] : repositoryNames

    return (
        <Combobox
            items={items}
            // Server-side search already filtered the list; don't let the combobox re-filter by input value.
            filter={null}
            value={value || null}
            onValueChange={(next: string | null) => onChange(next === NONE_SENTINEL ? null : next || null)}
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                setOpen(nextOpen)
                // Reset back to the full list on the next open rather than on close: clearing the search
                // while closing would empty the list and flip the trigger to a loading state for the
                // debounce window, flickering the picker every time it's dismissed after a search.
                if (nextOpen && trimmedSearchQuery.length > 0) {
                    setSearchQuery('')
                }
            }}
            inputValue={searchQuery}
            onInputValueChange={(next: string) => setSearchQuery(next)}
            disabled={disabled}
        >
            <ComboboxTrigger
                render={
                    <Button ref={triggerRef} variant="outline" size="sm" disabled={disabled} aria-label="Repository">
                        <IconGithub className="shrink-0" />
                        <span className="min-w-0 truncate">{value || placeholder}</span>
                    </Button>
                }
            />
            <ComboboxContent anchor={triggerRef} side="bottom" sideOffset={6} className="min-w-[280px]">
                <div className="flex min-w-0 items-center gap-1 pe-2">
                    <div className="min-w-0 flex-1">
                        <ComboboxInput placeholder="Search repositories..." />
                    </div>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={disabled || loading}
                                    aria-label="Refresh repositories"
                                    onMouseDown={(event: MouseEvent) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                    }}
                                    onClick={(event: MouseEvent) => {
                                        event.preventDefault()
                                        event.stopPropagation()
                                        refresh()
                                    }}
                                >
                                    <IconRefresh className={loading ? 'animate-spin' : undefined} />
                                </Button>
                            }
                        />
                        <TooltipContent>Refresh repositories</TooltipContent>
                    </Tooltip>
                </div>
                <ComboboxEmpty>
                    {showInlineLoadingState ? 'Loading repositories...' : error ? error : 'No repositories found.'}
                </ComboboxEmpty>
                <ComboboxList>
                    {(repo: string) =>
                        repo === NONE_SENTINEL ? (
                            <ComboboxItem key={repo} value={repo}>
                                No repository
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={repo} value={repo}>
                                {repo}
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>

                {hasMore && (
                    <ComboboxListFooter>
                        <div className="px-2 pb-2">
                            <div className="px-1 pb-2 text-center text-muted text-xs">
                                {`Showing ${repositoryNames.length}+ ${trimmedSearchQuery ? 'matches' : 'repositories'}`}
                            </div>
                            <Button
                                variant="outline"
                                size="sm"
                                className="w-full justify-center"
                                disabled={loading}
                                onMouseDown={(event: MouseEvent) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                }}
                                onClick={(event: MouseEvent) => {
                                    event.preventDefault()
                                    event.stopPropagation()
                                    loadMore()
                                }}
                            >
                                Load more
                            </Button>
                        </div>
                    </ComboboxListFooter>
                )}
            </ComboboxContent>
        </Combobox>
    )
}
