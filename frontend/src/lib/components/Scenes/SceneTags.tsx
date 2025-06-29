import { IconCheck, IconUndo } from '@posthog/icons'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { useEffect, useState } from 'react'
import { ObjectTags } from '../ObjectTags/ObjectTags'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

type SceneDescriptionProps = {
    isEditing: boolean
    onSave: (value: string[]) => void
    tags?: string[]
    tagsAvailable?: string[]
    dataAttr?: string
}

export function SceneTags({ isEditing, onSave, tags, tagsAvailable, dataAttr }: SceneDescriptionProps): JSX.Element {
    const [localTags, setLocalTags] = useState(tags)
    const [localIsEditing, setLocalIsEditing] = useState(isEditing)
    const [hasChanged, setHasChanged] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave(localTags ?? [])
        setHasChanged(false)
    }

    useEffect(() => {
        setLocalIsEditing(isEditing)
    }, [isEditing])

    useEffect(() => {
        setHasChanged(localTags !== tags)
    }, [localTags, tags])

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-tags" className="flex flex-col gap-2 relative">
            <LemonField.Pure label="Tags" className="gap-0">
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
                    className="pb-10" // Make room for the buttons hugging the bottom of the input
                />
            </LemonField.Pure>
            <div className="flex gap-1 absolute right-1 bottom-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update tags' : 'No changes to update'}
                    data-attr={`${dataAttr}-tags-update-button`}
                >
                    <IconCheck />
                </ButtonPrimitive>
                {hasChanged && (
                    <ButtonPrimitive
                        type="button"
                        variant="outline"
                        disabled={!hasChanged}
                        onClick={() => setLocalTags(tags)}
                        tooltip="Undo tags changes"
                        data-attr={`${dataAttr}-tags-undo-button`}
                    >
                        <IconUndo />
                    </ButtonPrimitive>
                )}
            </div>
        </form>
    ) : (
        <LemonField.Pure label="Tags" className="gap-0">
            <ObjectTags tags={tags ?? []} data-attr="scene-tags" staticOnly />
        </LemonField.Pure>
    )
}
