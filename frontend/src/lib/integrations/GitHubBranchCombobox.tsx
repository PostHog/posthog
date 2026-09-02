import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconGitBranch } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
} from '@posthog/quill'

import { ComboboxLoadMoreFooter, ComboboxSearchField } from './ComboboxSearchChrome'
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
    allowCustomValues?: boolean
}

/** Sentinel item value for the "type a new branch name" action. */
const CREATE_BRANCH_PREFIX = '__create__:'

/**
 * GitHub branch picker built on Quill's Combobox, mirroring the PostHog Desktop branch picker: a button
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
    allowCustomValues = true,
}: GitHubBranchComboboxProps): JSX.Element {
    const logic = githubBranchSearchLogic({ integrationId, repo })
    const { branches, defaultBranch, loading, hasMore, searchQuery, error } = useValues(logic)
    const { setSearchQuery, loadMore, refresh } = useActions(logic)

    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)
    const preselectRequestedFor = useRef<string | null>(null)

    const trimmedSearchQuery = searchQuery.trim()
    const showInlineLoadingState = open && loading

    // Pre-select the repo's default branch once it's known and nothing is chosen yet (matches PostHog Desktop).
    // Only a picker still missing a branch pays for the upfront fetch that surfaces it. One that already has
    // its branch stays lazy, so a list of them doesn't fire a request per row.
    useEffect(() => {
        if (value) {
            return
        }
        if (defaultBranch) {
            onChange(defaultBranch)
            return
        }
        const repoKey = `${integrationId}:${repo}`
        if (preselectRequestedFor.current !== repoKey) {
            preselectRequestedFor.current = repoKey
            refresh()
        }
    }, [value, defaultBranch, onChange, refresh, integrationId, repo])

    // Offer "Use <typed> as branch name" when the search doesn't match an existing branch — lets the agent
    // work on a brand-new branch.
    const createSentinel = CREATE_BRANCH_PREFIX + trimmedSearchQuery
    const showCreateItem =
        allowCustomValues && trimmedSearchQuery.length > 0 && !loading && !branches.includes(trimmedSearchQuery)
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
                if (!nextOpen) {
                    return
                }
                // Reset back to the full list on the next open rather than on close, matching
                // GitHubRepositoryCombobox: clearing the search while closing fetches an unfiltered page
                // for a list nobody is looking at.
                if (trimmedSearchQuery.length > 0) {
                    setSearchQuery('')
                } else if (branches.length === 0 && !loading) {
                    refresh()
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
                <ComboboxSearchField itemsLabel="branches" loading={loading} disabled={disabled} onRefresh={refresh} />
                <ComboboxEmpty>
                    {showInlineLoadingState ? 'Loading branches...' : (error ?? 'No branches found.')}
                </ComboboxEmpty>
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
                    <ComboboxLoadMoreFooter
                        loadedCount={branches.length}
                        itemsLabel="branches"
                        searching={!!trimmedSearchQuery}
                        loading={loading}
                        onLoadMore={loadMore}
                    />
                )}
            </ComboboxContent>
        </Combobox>
    )
}
