import { useActions, useValues } from 'kea'

import { TypesafeSuggestButton } from 'lib/components/TypesafeSuggest/TypesafeSuggestButton'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { tagsModel } from '~/models/tagsModel'

import { TagsCombobox } from './TagsCombobox'
import { SceneCanEditProps, SceneDataAttrKeyProps } from './utils'

type SceneTagsComboboxProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        onSave?: (value: string[]) => void
        tags?: string[]
        tagsAvailable?: string[]
        loading?: boolean
        /** Asks TypeSafe which of the team's existing tags apply. Renders a sparkle button in the label. */
        onSuggest?: () => void
        suggesting?: boolean
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
    onSuggest,
    suggesting = false,
}: SceneTagsComboboxProps): JSX.Element {
    const { tags: allExistingTags, tagsLoading } = useValues(tagsModel)
    const { loadTagsIfNeeded } = useActions(tagsModel)
    const label = (
        <span className="flex items-center gap-1.5">
            Tags
            {loading || tagsLoading ? <Spinner className="text-sm" /> : null}
            {onSuggest && canEdit && onSave ? (
                <TypesafeSuggestButton
                    label="Suggest tags with TypeSafe"
                    onClick={onSuggest}
                    loading={suggesting}
                    dataAttr={`${dataAttrKey}-tags-typesafe-suggest`}
                    size="xsmall"
                />
            ) : null}
        </span>
    )

    return (
        <ScenePanelLabel title={label}>
            <TagsCombobox
                value={tags ?? []}
                onChange={(next) => onSave?.(next)}
                onOpen={loadTagsIfNeeded}
                loading={tagsLoading}
                options={tagsAvailable ?? allExistingTags.filter((tag) => !tags?.includes(tag))}
                placeholder="Add tags..."
                disabled={!onSave || !canEdit}
                allowCustomValues
                customValueNoun="tag"
                dataAttr={`${dataAttrKey}-tags-input`}
            />
        </ScenePanelLabel>
    )
}
