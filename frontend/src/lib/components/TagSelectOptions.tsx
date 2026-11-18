import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { TagOption } from './tagSelectLogic'

export function TagSelectOptions({
    displayedTags,
    value,
    loading,
    tagPageError,
    search,
    onToggle,
}: {
    displayedTags: TagOption[]
    value: string[]
    loading: boolean
    tagPageError: boolean
    search: string
    onToggle: (tag: string) => void
}): JSX.Element {
    return (
        <ul className="deprecated-space-y-px p-1">
            {displayedTags.map(({ tag, count }) => (
                <li key={tag}>
                    <LemonButton
                        fullWidth
                        role="checkbox"
                        aria-checked={value.includes(tag)}
                        aria-label={count === undefined ? tag : `${tag} (${count})`}
                        tooltip={tag}
                        size="small"
                        onClick={() => onToggle(tag)}
                    >
                        <span className="flex min-w-0 flex-1 items-center gap-2 text-left">
                            <LemonCheckbox checked={value.includes(tag)} decorative className="pointer-events-none" />
                            <span className="min-w-0 flex-1 truncate" title={tag}>
                                {tag}
                            </span>
                            {count !== undefined && <span className="text-muted tabular-nums">{count}</span>}
                        </span>
                    </LemonButton>
                </li>
            ))}
            {loading && !tagPageError && (
                <li className="p-1" aria-label="Loading tags">
                    <LemonSkeleton.Row className="h-8 mb-1" repeat={displayedTags.length === 0 ? 5 : 2} fade />
                </li>
            )}
            {!loading && !tagPageError && displayedTags.length === 0 && (
                <li className="p-2 text-secondary italic">{search ? 'No matching tags' : 'No tags'}</li>
            )}
        </ul>
    )
}
