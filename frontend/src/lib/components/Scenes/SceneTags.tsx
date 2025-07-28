import { IconCheck, IconX } from '@posthog/icons'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { useEffect, useState } from 'react'
import { ObjectTags } from '../ObjectTags/ObjectTags'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { SceneCanEditProps, SceneDataAttrKeyProps } from './utils'

type SceneTagsProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        onSave?: (value: string[]) => void
        tags?: string[]
        tagsAvailable?: string[]
    }

export function SceneTags({ onSave, tags, tagsAvailable, dataAttrKey, canEdit = true }: SceneTagsProps): JSX.Element {
    const [localTags, setLocalTags] = useState(tags)
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [hasChanged, setHasChanged] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave?.(localTags ?? [])
        setHasChanged(false)
        setLocalIsEditing(false)
    }

    useEffect(() => {
        setHasChanged(localTags !== tags)
    }, [localTags, tags])

    useEffect(() => {
        setLocalTags(tags)
    }, [tags])

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-tags" className="flex flex-col gap-1">
            <ScenePanelLabel htmlFor="new-tag-input" title="Tags">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={localTags}
                    options={tagsAvailable?.map((t) => ({ key: t, label: t }))}
                    onChange={setLocalTags}
                    loading={false}
                    data-attr={`${dataAttrKey}-new-tag-input`}
                    placeholder='try "official"'
                    size="xsmall"
                    autoFocus
                />
            </ScenePanelLabel>
            <div className="flex gap-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update tags' : 'No changes to update'}
                    data-attr={`${dataAttrKey}-tags-update-button`}
                >
                    <IconCheck />
                </ButtonPrimitive>
                <ButtonPrimitive
                    type="button"
                    variant="outline"
                    onClick={() => {
                        setLocalTags(tags)
                        setLocalIsEditing(false)
                    }}
                    tooltip="Cancel"
                    data-attr={`${dataAttrKey}-tags-undo-button`}
                >
                    <IconX />
                </ButtonPrimitive>
            </div>
        </form>
    ) : (
        <ScenePanelLabel title="Tags">
            <ButtonPrimitive
                className="hyphens-auto flex gap-1 items-center"
                lang="en"
                onClick={() => onSave && canEdit && setLocalIsEditing(true)}
                tooltip={canEdit ? 'Edit tags' : 'Tags are read-only'}
                autoHeight
                menuItem
                inert={!canEdit}
                data-attr={`${dataAttrKey}-tags-button`}
            >
                {tags && tags.length > 0 ? (
                    <ObjectTags tags={tags} data-attr={`${dataAttrKey}-tags`} staticOnly />
                ) : (
                    <>
                        {onSave && canEdit ? (
                            'Click to add tags'
                        ) : (
                            <span className="text-tertiary font-normal">No tags</span>
                        )}
                    </>
                )}
            </ButtonPrimitive>
        </ScenePanelLabel>
    )
}
