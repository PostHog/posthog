import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { AvailableFeature } from '~/types'

import { ObjectTags } from '../ObjectTags/ObjectTags'
import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'
import { SceneCanEditProps, SceneDataAttrKeyProps, SceneSaveCancelButtons } from './utils'

type SceneTagsProps = SceneCanEditProps &
    SceneDataAttrKeyProps & {
        onSave?: (value: string[]) => void
        tags?: string[]
        tagsAvailable?: string[]
    }

export const SceneTags = ({
    onSave,
    tags,
    tagsAvailable,
    dataAttrKey,
    canEdit = true,
}: SceneTagsProps): JSX.Element => {
    const [localTags, setLocalTags] = useState(tags)
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [hasChanged, setHasChanged] = useState(false)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    const onGuardClick = (callback: () => void): void => {
        guardAvailableFeature(AvailableFeature.TAGGING, () => {
            callback()
        })
    }

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
            <SceneSaveCancelButtons
                name="tags"
                onCancel={() => {
                    setLocalTags(tags)
                    setLocalIsEditing(false)
                }}
                hasChanged={hasChanged}
                dataAttrKey={dataAttrKey}
            />
        </form>
    ) : (
        <ScenePanelLabel title="Tags">
            <ButtonPrimitive
                className="hyphens-auto flex gap-1 items-center"
                lang="en"
                onClick={() => onSave && canEdit && onGuardClick(() => setLocalIsEditing(true))}
                tooltip={canEdit ? 'Edit tags' : 'Tags are read-only'}
                autoHeight
                menuItem
                inert={!canEdit}
                data-attr={`${dataAttrKey}-tags-button`}
                variant="panel"
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
