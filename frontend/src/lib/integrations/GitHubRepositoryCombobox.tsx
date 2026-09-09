import { useActions, useValues } from 'kea'
import { useRef, useState } from 'react'

import { IconGithub } from '@posthog/icons'
import {
    Button,
    Combobox,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxItem,
    ComboboxList,
    ComboboxTrigger,
} from '@posthog/quill'

import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'

import { ComboboxLoadMoreFooter, ComboboxSearchField } from './ComboboxSearchChrome'
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
    repositoryFilter?: (repository: GitHubRepoApi) => boolean
    fullWidth?: boolean
}

/**
 * GitHub repository picker built on Quill's Combobox, mirroring the PostHog Desktop repo picker: a button
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
    repositoryFilter,
    fullWidth = false,
}: GitHubRepositoryComboboxProps): JSX.Element {
    const logic = githubRepositorySearchLogic({ id: integrationId })
    const { repositories, loading, hasMore, searchQuery, error } = useValues(logic)
    const repositoryNames = (repositoryFilter ? repositories.filter(repositoryFilter) : repositories).map(
        (repo) => repo.full_name
    )
    const { setSearchQuery, loadMore, refresh } = useActions(logic)

    const triggerRef = useRef<HTMLButtonElement>(null)
    const [open, setOpen] = useState(false)

    const trimmedSearchQuery = searchQuery.trim()
    // Keep the selected target visible while searching, loading, or refreshing.
    const showInlineLoadingState = open && loading

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
                    <Button
                        ref={triggerRef}
                        variant="outline"
                        size="sm"
                        disabled={disabled}
                        aria-label="Repository"
                        className={fullWidth ? 'min-h-10 w-full justify-start' : undefined}
                    >
                        <IconGithub className="shrink-0" />
                        <span className="min-w-0 truncate">{value || placeholder}</span>
                    </Button>
                }
            />
            <ComboboxContent anchor={triggerRef} side="bottom" sideOffset={6} className="min-w-[280px]">
                <ComboboxSearchField
                    itemsLabel="repositories"
                    loading={loading}
                    disabled={disabled}
                    onRefresh={refresh}
                />
                <ComboboxEmpty>
                    {showInlineLoadingState ? 'Loading repositories...' : (error ?? 'No repositories found.')}
                </ComboboxEmpty>
                <ComboboxList>
                    {(repo: string) =>
                        repo === NONE_SENTINEL ? (
                            <ComboboxItem key={repo} value={repo}>
                                No repository
                            </ComboboxItem>
                        ) : (
                            <ComboboxItem key={repo} value={repo}>
                                <span className="min-w-0 break-all">{repo}</span>
                            </ComboboxItem>
                        )
                    }
                </ComboboxList>

                {hasMore && (
                    <ComboboxLoadMoreFooter
                        loadedCount={repositoryNames.length}
                        itemsLabel="repositories"
                        searching={!!trimmedSearchQuery}
                        loading={loading}
                        onLoadMore={loadMore}
                    />
                )}
            </ComboboxContent>
        </Combobox>
    )
}
