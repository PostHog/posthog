import { Spinner } from 'lib/lemon-ui/Spinner'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { TagsCombobox } from './TagsCombobox'
import { SceneCanEditProps, SceneDataAttrKeyProps } from './utils'

type SceneTagsComboboxProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        onSave?: (value: string[]) => void
        tags?: string[]
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
    const label = (
        <span className="flex items-center gap-1.5">
            Tags
            {loading ? <Spinner className="text-sm" /> : null}
        </span>
    )

    return (
        <ScenePanelLabel title={label}>
            <TagsCombobox
                value={tags ?? []}
                onChange={(next) => onSave?.(next)}
                options={tagsAvailable}
                placeholder="Add tags..."
                disabled={!onSave || !canEdit}
                allowCustomValues
                customValueNoun="tag"
                dataAttr={`${dataAttrKey}-tags-input`}
            />
        </ScenePanelLabel>
    )
}
