import { useId, useMemo } from 'react'

import { cn } from '@posthog/quill'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import type { LoadTags, TagObjectType } from 'lib/components/tagSelectLogic'
import { useTagPages } from 'lib/components/useTagPages'

export function QuillObjectTagsEditor({
    tags,
    onChange,
    onStopEditing,
    saving,
    tagsAvailable,
    loadTags,
    objectType,
    placeholder,
    fullWidth,
}: {
    tags: string[]
    onChange: (tags: string[]) => void
    onStopEditing: () => void
    saving?: boolean
    /** Fixed suggestions. Leave out to suggest the project's tags, loaded a page at a time. */
    tagsAvailable?: string[]
    loadTags?: LoadTags
    objectType?: TagObjectType
    placeholder: string
    fullWidth: boolean
}): JSX.Element {
    const tagPages = useTagPages(useId(), loadTags, objectType)
    const pagesLoading = tagPages.awaitingFirstPage || tagPages.pageLoading
    const optionsByTag = useMemo(
        () => Object.fromEntries(tagPages.tags.map((option) => [option.tag, option])),
        [tagPages.tags]
    )

    // The combobox keeps focus in its input while its list is open, so focus leaving both ends the edit.
    const stopEditingOnFocusOut = (event: React.FocusEvent<HTMLDivElement>): void => {
        const next = event.relatedTarget as Element | null
        if (next && (event.currentTarget.contains(next) || next.closest('[data-slot="combobox-content"]'))) {
            return
        }
        onStopEditing()
    }

    return (
        <div className={cn('min-w-60', fullWidth && 'w-full')} onBlur={stopEditingOnFocusOut}>
            {tagsAvailable ? (
                <TagsCombobox
                    value={tags}
                    onChange={onChange}
                    options={tagsAvailable.filter((tag) => !tags.includes(tag))}
                    loading={saving}
                    placeholder={placeholder}
                    autoFocus
                    allowCustomValues
                    dataAttr="new-tag-input"
                />
            ) : (
                <TagsCombobox
                    value={tags}
                    onChange={onChange}
                    onOpen={() => tagPages.setOpen(true)}
                    onClose={() => tagPages.setOpen(false)}
                    onInputChange={tagPages.setSearch}
                    loading={saving || pagesLoading}
                    options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !tags.includes(tag))}
                    optionsByTag={optionsByTag}
                    error={tagPages.error ? "Couldn't load tags." : undefined}
                    onRetry={tagPages.retry}
                    onScrollEnd={tagPages.loadMore}
                    loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                    placeholder={placeholder}
                    autoFocus
                    allowCustomValues
                    dataAttr="new-tag-input"
                />
            )}
        </div>
    )
}
