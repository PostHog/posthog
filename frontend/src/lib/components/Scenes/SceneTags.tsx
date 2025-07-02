import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { useEffect, useState } from 'react'
import { ObjectTags } from '../ObjectTags/ObjectTags'

type SceneDescriptionProps = {
    onSave: (value: string[]) => void
    tags?: string[]
    tagsAvailable?: string[]
    dataAttr?: string
}

export function SceneTags({ onSave, tags, tagsAvailable, dataAttr }: SceneDescriptionProps): JSX.Element {
    const [localTags, setLocalTags] = useState(tags)
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [hasChanged, setHasChanged] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave(localTags ?? [])
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
            <div className="gap-0">
                <Label intent="menu" htmlFor="new-tag-input">
                    Tags
                </Label>
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={localTags}
                    options={tagsAvailable?.map((t) => ({ key: t, label: t }))}
                    onChange={setLocalTags}
                    loading={false}
                    data-attr="new-tag-input"
                    placeholder='try "official"'
                    size="xsmall"
                    autoFocus
                />
            </div>
            <div className="flex gap-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update tags' : 'No changes to update'}
                    data-attr={`${dataAttr}-tags-update-button`}
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
                    data-attr={`${dataAttr}-tags-undo-button`}
                >
                    <IconX />
                </ButtonPrimitive>
            </div>
        </form>
    ) : (
        <div className="gap-0">
            <Label intent="menu">Tags</Label>
            <div className="flex gap-1 items-center">
                <ObjectTags tags={tags ?? []} data-attr="scene-tags" staticOnly />
                <ButtonPrimitive iconOnly onClick={() => setLocalIsEditing(true)} className="inline-block" size="sm">
                    <IconPencil />
                </ButtonPrimitive>
            </div>
        </div>
    )
}
