import { useId } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { useTagPages } from '../useTagPages'
import { TagsCombobox } from './TagsCombobox'
import { SceneCanEditProps, SceneDataAttrKeyProps } from './utils'

type SceneTagsComboboxProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        onSave?: (value: string[]) => void
        tags?: string[]
        loading?: boolean
    }

/**
 * Quill-Combobox variant of `<SceneTags>`. Always-rendered input + chips, with autosave on change.
 * Gate behind the `SCENE_MENU_BAR` feature flag at call sites.
 */
export function SceneTagsCombobox({
    onSave,
    tags,
    dataAttrKey,
    canEdit = true,
    loading,
}: SceneTagsComboboxProps): JSX.Element {
    const tagPages = useTagPages(useId())
    const tagsLoading = tagPages.awaitingFirstPage || tagPages.pageLoading
    const label = (
        <span className="flex items-center gap-1.5">
            Tags
            {loading || tagsLoading ? <Spinner className="text-sm" /> : null}
        </span>
    )

    return (
        <ScenePanelLabel title={label}>
            <TagsCombobox
                value={tags ?? []}
                onChange={(next) => onSave?.(next)}
                onOpen={() => tagPages.setOpen(true)}
                onClose={() => tagPages.setOpen(false)}
                onInputChange={tagPages.setSearch}
                loading={tagsLoading}
                options={tagPages.tags.map(({ tag }) => tag).filter((tag) => !tags?.includes(tag))}
                error={tagPages.error ? "Couldn't load tags." : undefined}
                onRetry={tagPages.retry}
                onScrollEnd={tagPages.loadMore}
                loadingMore={tagPages.pageLoading && tagPages.tags.length > 0}
                placeholder="Add tags..."
                disabled={!onSave || !canEdit}
                allowCustomValues
                customValueNoun="tag"
                dataAttr={`${dataAttrKey}-tags-input`}
            />
        </ScenePanelLabel>
    )
}
