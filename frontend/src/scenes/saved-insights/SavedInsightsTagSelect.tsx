import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { useScrollObserver } from 'lib/hooks/useScrollObserver'

import { savedInsightsTagFilterLogic } from './savedInsightsTagFilterLogic'

export function SavedInsightsTagSelect({
    value,
    onChange,
    borderless = false,
}: {
    value: string[]
    onChange: (value: string[]) => void
    borderless?: boolean
}): JSX.Element {
    const fallbackKey = useId()
    const logic = savedInsightsTagFilterLogic({ logicKey: fallbackKey })
    const { tagPageError, tagPageLoading, tagResults, tagSearch } = useValues(logic)
    const { loadMoreTagResults, retryTagResults, setTagPopoverOpen, setTagSearch } = useActions(logic)
    const tagListScrollRef = useScrollObserver({ onScrollBottom: loadMoreTagResults })
    const displayedTags = Array.from(new Set([...value, ...tagResults]))

    const handleTagToggle = (tag: string): void => {
        const selected = new Set(value)
        if (selected.has(tag)) {
            selected.delete(tag)
        } else {
            selected.add(tag)
        }
        onChange(Array.from(selected))
    }

    return (
        <LemonDropdown
            closeOnClickInside={false}
            matchWidth={false}
            actionable
            onVisibilityChange={setTagPopoverOpen}
            overlay={
                <div className="max-w-100 deprecated-space-y-2">
                    <LemonInput
                        type="search"
                        placeholder="Search tags"
                        autoFocus
                        value={tagSearch}
                        onChange={setTagSearch}
                        fullWidth
                        className="max-w-full"
                    />
                    <div
                        ref={tagListScrollRef}
                        className="max-h-80 overflow-y-auto"
                        data-attr="saved-insights-tags-list"
                    >
                        <ul className="deprecated-space-y-px">
                            {displayedTags.map((tag) => (
                                <li key={tag}>
                                    <LemonButton
                                        fullWidth
                                        role="menuitem"
                                        size="small"
                                        onClick={() => handleTagToggle(tag)}
                                    >
                                        <span className="flex items-center gap-2 max-w-full">
                                            <input
                                                type="checkbox"
                                                className="cursor-pointer"
                                                checked={value.includes(tag)}
                                                readOnly
                                            />
                                            <span>{tag}</span>
                                        </span>
                                    </LemonButton>
                                </li>
                            ))}
                            {!tagPageLoading && !tagPageError && tagResults.length === 0 ? (
                                <li className="p-2 text-secondary italic truncate border-t">
                                    {tagSearch ? 'No matching tags' : 'No tags'}
                                </li>
                            ) : null}
                            {tagPageLoading ? <li className="p-2 text-secondary">Loading tags...</li> : null}
                        </ul>
                    </div>
                    {tagPageError && (
                        <LemonButton
                            fullWidth
                            size="small"
                            type="secondary"
                            loading={tagPageLoading}
                            onClick={retryTagResults}
                        >
                            Couldn't load tags. Try again.
                        </LemonButton>
                    )}
                    {value.length > 0 && (
                        <LemonButton
                            fullWidth
                            role="menuitem"
                            size="small"
                            onClick={() => onChange([])}
                            type="secondary"
                        >
                            Clear selection
                        </LemonButton>
                    )}
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                active={value.length > 0}
                status={borderless && value.length === 0 ? 'alt' : 'default'}
            >
                {value.length > 0 ? `Tags (${value.length})` : 'Tags'}
            </LemonButton>
        </LemonDropdown>
    )
}
