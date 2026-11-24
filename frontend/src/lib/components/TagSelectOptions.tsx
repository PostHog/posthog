import { LemonButton, LemonCheckbox } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import { TagOptionLabel } from './TagOptionLabel'
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
            {displayedTags.map((option) => (
                <li key={option.tag}>
                    <LemonButton
                        fullWidth
                        role="checkbox"
                        aria-checked={value.includes(option.tag)}
                        aria-label={option.count === undefined ? option.tag : `${option.tag} (${option.count})`}
                        // The count carries its own usage tooltip, which a row-wide tooltip would cover.
                        tooltip={option.total_count === undefined ? option.tag : undefined}
                        size="small"
                        onClick={() => onToggle(option.tag)}
                    >
                        <span className="flex min-w-0 flex-1 items-center gap-2 text-left">
                            <LemonCheckbox
                                checked={value.includes(option.tag)}
                                decorative
                                className="pointer-events-none"
                            />
                            <TagOptionLabel {...option} />
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
