import { IconCheck, IconX } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'

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
            <div className="flex flex-col gap-0">
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
                    className="-ml-1.5"
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
            <div className="-ml-1.5">
                <ButtonPrimitive
                    className="hyphens-auto flex gap-1 items-center"
                    lang="en"
                    onClick={() => setLocalIsEditing(true)}
                    tooltip="Edit description"
                    autoHeight
                    menuItem
                >
                    {defaultValue || <span className="text-tertiary font-normal">Description (optional)</span>}
                </ButtonPrimitive>
            </div>
        </div>
    )
}
