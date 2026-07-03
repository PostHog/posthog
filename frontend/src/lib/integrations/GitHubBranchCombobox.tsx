import { useActions, useValues } from 'kea'
import { type MouseEvent, useEffect, useRef, useState } from 'react'

import { IconGitBranch, IconRefresh } from '@posthog/icons'
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

import { githubBranchSearchLogic } from './githubBranchSearchLogic'

export interface GitHubBranchComboboxProps {
    integrationId: number
    /** Repository in `owner/repo` format whose branches to list. */
    repo: string
    /** Selected branch name, or empty when nothing is picked. */
    value: string
    onChange: (value: string | null) => void
    disabled?: boolean
    placeholder?: string
}

/** Sentinel item value for the "type a new branch name" action. */
const CREATE_BRANCH_PREFIX = '__create__:'

/**
 * GitHub branch picker built on Quill's Combobox, mirroring the PostHog Code branch picker: a button
 * trigger, in-popover server-side search, a paginated "Load more" footer, and a refresh control. It
 * auto-selects the repository's default branch, and lets the user type a brand-new branch name (committed
 * via a synthetic "Use \"x\" as branch name" item). Searching/pagination are delegated to
 * {@link githubBranchSearchLogic}, keyed per repository.
 */
export function GitHubBranchCombobox({
    integrationId,
    repo,
    value,
    onChange,
    disabled = false,
    placeholder = 'Select branch...',
}: GitHubBranchComboboxProps): JSX.Element {
    const logic = githubBranchSearchLogic({ integrationId, repo })
    const { branches, defaultBranch, loading, hasMore, searchQuery } = useValues(logic)
    const { setSearchQuery, loadMore, refresh } = useActions(logic)

    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    const trimmedSearchQuery = searchQuery.trim()
    const showInlineLoadingState = open && loading

    // Pre-select the repo's default branch once it's known and nothing is chosen yet (matches PostHog Code).
    useEffect(() => {
        if (!value && defaultBranch) {
            onChange(defaultBranch)
        }
    }, [value, defaultBranch, onChange])

    // Offer "Use <typed> as branch name" when the search doesn't match an existing branch — lets the agent
    // work on a brand-new branch.
    const createSentinel = CREATE_BRANCH_PREFIX + trimmedSearchQuery
    const showCreateItem = trimmedSearchQuery.length > 0 && !loading && !branches.includes(trimmedSearchQuery)
    const items = showCreateItem ? [...branches, createSentinel] : branches

    return (
        <Combobox
            items={items}
            // Server-side search already filtered the list; don't let the combobox re-filter by input value.
            filter={null}
            value={value || null}
            onValueChange={(next: string | null) => {
                if (!next) {
                    onChange(null)
                    return
                }
                onChange(next.startsWith(CREATE_BRANCH_PREFIX) ? next.slice(CREATE_BRANCH_PREFIX.length) : next)
            }}
            open={open}
            onOpenChange={(nextOpen: boolean) => {
                setOpen(nextOpen)
                if (!nextOpen && trimmedSearchQuery.length > 0) {
                    setSearchQuery('')
                }
            }}
            inputValue={searchQuery}
            onInputValueChange={(next: string) => setSearchQuery(next)}
            disabled={disabled}
        >
            <ComboboxTrigger
                render={
                    <Button ref={triggerRef} variant="outline" size="sm" disabled={disabled} aria-label="Branch">
                        <IconGitBranch className="shrink-0" />
                        <span className="min-w-0 truncate">{value || placeholder}</span>
                    </Button>
                }
            />
            <ComboboxContent anchor={triggerRef} side="bottom" sideOffset={6} className="min-w-[280px]">
                <div className="flex min-w-0 items-center gap-1 pe-2">
                    <div className="min-w-0 flex-1">
                        <ComboboxInput placeholder="Search branches..." />
                    </div>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="outline"
                                    size="sm"
                                    disabled={disabled || loading}
                                    aria-label="Refresh branches"
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
                        <TooltipContent>Refresh branches</TooltipContent>
                    </Tooltip>
                </div>
                <ComboboxEmpty>{showInlineLoadingState ? 'Loading branches...' : 'No branches found.'}</ComboboxEmpty>
                <ComboboxList>
                    {(item: string) =>
                        item.startsWith(CREATE_BRANCH_PREFIX) ? (
                            <ComboboxItem key={item} value={item}>
                                Use "{trimmedSearchQuery}" as branch name
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={item} value={item}>
                                {item}
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>

                {hasMore && (
                    <ComboboxListFooter>
                        <div className="px-2 pb-2">
                            <div className="px-1 pb-2 text-center text-muted text-xs">
                                {`Showing ${branches.length}+ ${trimmedSearchQuery ? 'matches' : 'branches'}`}
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
