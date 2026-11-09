import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'

import { useTagPages } from '../useTagPages'
import { TagsCombobox } from './TagsCombobox'
import { SceneCanEditProps, SceneDataAttrKeyProps } from './utils'

type SceneTagsComboboxProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        onSave?: (value: string[]) => void
        tags?: string[]
        /** Fixed suggestions. Leave out to suggest the project's tags, loaded a page at a time. */
        tagsAvailable?: string[]
        loading?: boolean
    }

/**
 * Quill-Combobox variant of `<SceneTags>`. Always-rendered input + chips, with autosave on change.
 * Gate behind the `SCENE_MENU_BAR` feature flag at call sites.
 */
export function SceneTagsCombobox({
    onSave,
    tags,
    tagsAvailable,
    dataAttrKey,
    canEdit = true,
    loading,
}: SceneTagsComboboxProps): JSX.Element {
    const tagPages = useTagPages(useId())
    // Callers that pass `tagsAvailable` read it from `tagsModel`, which loads only when asked. Remove with `tagsModel`.
    const { tagsLoading: modelLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)
    const tagsLoading = tagsAvailable ? modelLoading : tagPages.awaitingFirstPage || tagPages.pageLoading
    const label = (
        <span className="flex items-center gap-1.5">
            Tags
            {loading || tagsLoading ? <Spinner className="text-sm" /> : null}
        </span>
    )
    const comboboxProps = tagsAvailable
        ? { options: tagsAvailable, onOpen: loadTagsIfNeeded }
        : {
              options: tagPages.tags.map(({ tag }) => tag).filter((tag) => !tags?.includes(tag)),
              onOpen: () => tagPages.setOpen(true),
              onClose: () => tagPages.setOpen(false),
              onInputChange: tagPages.setSearch,
              error: tagPages.error ? "Couldn't load tags." : undefined,
              onRetry: tagPages.retry,
              onScrollEnd: tagPages.loadMore,
              loadingMore: tagPages.pageLoading && tagPages.tags.length > 0,
          }

    return (
        <ScenePanelLabel title={label}>
            <TagsCombobox
                value={tags ?? []}
                onChange={(next) => onSave?.(next)}
                loading={tagsLoading}
                {...comboboxProps}
                placeholder="Add tags..."
                disabled={!onSave || !canEdit}
                allowCustomValues
                customValueNoun="tag"
                dataAttr={`${dataAttrKey}-tags-input`}
            />
        </ScenePanelLabel>
    )
}
