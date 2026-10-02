import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { TagOption } from './tagSelectLogic'
import { TagSelectOptions } from './TagSelectOptions'

function tagStatus(error: boolean, loading: boolean, displayedTags: TagOption[], search: string): string {
    if (error) {
        return "Couldn't load tags. Try again."
    }
    if (loading) {
        return 'Loading tags'
    }
    if (displayedTags.length === 0) {
        return search ? 'No matching tags' : 'No tags'
    }
    return search ? `${displayedTags.length} tags shown` : ''
}

export function TagSelectMenu({
    search,
    setSearch,
    displayedTags,
    value,
    awaitingFirstPage,
    tagPageLoading,
    tagPageError,
    listDataAttr,
    scrollRef,
    onToggle,
    onRetry,
    onClear,
}: {
    search: string
    setSearch: (search: string) => void
    displayedTags: TagOption[]
    value: string[]
    awaitingFirstPage: boolean
    tagPageLoading: boolean
    tagPageError: string | null
    listDataAttr?: string
    scrollRef: (element: HTMLDivElement | null) => void
    onToggle: (tag: string) => void
    onRetry: () => void
    onClear: () => void
}): JSX.Element {
    const loading = tagPageLoading || awaitingFirstPage
    const hasVisibleSelection = displayedTags.some(({ tag }) => value.includes(tag))

    return (
        <div className="w-64 max-w-[min(25rem,80vw)]">
            <div className="border-b border-primary focus-within:ring-2 focus-within:ring-inset focus-within:ring-primary">
                <LemonInput
                    type="search"
                    placeholder="Search tags"
                    autoFocus
                    value={search}
                    onChange={setSearch}
                    fullWidth
                    className="!rounded-none !border-0 !bg-transparent !shadow-none"
                />
            </div>
            <span role="status" className="sr-only">
                {tagStatus(Boolean(tagPageError), loading, displayedTags, search)}
            </span>
            <div ref={scrollRef} className="max-h-80 overflow-y-auto" data-attr={listDataAttr}>
                <TagSelectOptions
                    displayedTags={displayedTags}
                    value={value}
                    loading={loading}
                    tagPageError={Boolean(tagPageError)}
                    search={search}
                    onToggle={onToggle}
                />
            </div>
            {(tagPageError || hasVisibleSelection) && (
                <div className="border-t border-primary">
                    {tagPageError && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="tertiary"
                            className="!rounded-none"
                            loading={tagPageLoading}
                            onClick={onRetry}
                        >
                            Couldn't load tags. Try again.
                        </LemonButton>
                    )}
                    {hasVisibleSelection && (
                        <LemonButton fullWidth size="small" type="tertiary" className="!rounded-none" onClick={onClear}>
                            Clear selection
                        </LemonButton>
                    )}
                </div>
            )}
        </div>
    )
}
