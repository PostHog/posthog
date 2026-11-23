import { useId } from 'react'

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { useTagPages } from 'lib/components/useTagPages'

import { SceneSettingsRow } from './SceneSettingsRow'

export interface SceneTagsRowProps {
    tags: string[] | undefined
    onSave: (tags: string[]) => void
    disabledReason?: string | null
    description?: string
    dataAttr?: string
}

export function SceneTagsRow({ tags, onSave, disabledReason, description, dataAttr }: SceneTagsRowProps): JSX.Element {
    const id = useId()
    const tagPages = useTagPages(id)
    const tagsLoading = tagPages.awaitingFirstPage || tagPages.pageLoading

    return (
        <SceneSettingsRow label="Tags" description={description} htmlFor={id}>
            <TagsCombobox
                id={id}
                className="w-full"
                value={tags ?? []}
                onChange={onSave}
                onOpen={() => tagPages.setOpen(true)}
                onClose={() => tagPages.setOpen(false)}
                onInputChange={tagPages.setSearch}
                loading={tagsLoading}
                options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !tags?.includes(tag))}
                error={tagPages.error ? "Couldn't load tags." : undefined}
                onRetry={tagPages.retry}
                onScrollEnd={tagPages.loadMore}
                loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                placeholder="Add tags"
                disabledReason={disabledReason ?? undefined}
                allowCustomValues
                customValueNoun="tag"
                dataAttr={dataAttr}
            />
        </SceneSettingsRow>
    )
}
