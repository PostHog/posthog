import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'
import { Label } from 'lib/ui/Label/Label'

type SceneDescriptionProps = {
    defaultValue: string
    onSave: (value: string) => void
    dataAttr?: string
}

export function SceneDescription({ defaultValue, onSave, dataAttr }: SceneDescriptionProps): JSX.Element {
    const [localValue, setLocalValue] = useState(defaultValue)
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [hasChanged, setHasChanged] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave(localValue)
        setHasChanged(false)
        setLocalIsEditing(false)
    }

    useEffect(() => {
        setHasChanged(localValue !== defaultValue)
    }, [localValue, defaultValue])

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-description-form" className="flex flex-col gap-1">
            <div className="gap-0">
                <Label intent="menu" htmlFor="page-description-input">
                    Description
                </Label>
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder="Description (optional)"
                    id="page-description-input"
                    data-attr={`${dataAttr}-description-input`}
                    autoFocus
                />
            </div>
            <div className="flex gap-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update description' : 'No changes to update'}
                    data-attr={`${dataAttr}-description-update-button`}
                >
                    <IconCheck />
                </ButtonPrimitive>
                <ButtonPrimitive
                    type="button"
                    variant="outline"
                    onClick={() => {
                        setLocalValue(defaultValue)
                        setLocalIsEditing(false)
                    }}
                    tooltip="Cancel"
                >
                    <IconX />
                </ButtonPrimitive>
            </div>
        </form>
    ) : (
        <div className="gap-0">
            <Label intent="menu">Description</Label>
            <p className="m-0 hyphens-auto flex gap-1 items-center" lang="en">
                {defaultValue || <span className="text-tertiary font-normal">No description</span>}
                <ButtonPrimitive iconOnly onClick={() => setLocalIsEditing(true)} className="inline-block" size="sm">
                    <IconPencil />
                </ButtonPrimitive>
            </p>
        </div>
    )
}
