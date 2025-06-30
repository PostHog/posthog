import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimtive/TextareaPrimitive'
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
            <LemonField.Pure label="Description" className="gap-0" htmlFor="page-description-input">
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
            </LemonField.Pure>
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
        <LemonField.Pure label="Description" className="gap-0">
            <p className="m-0 hyphens-auto flex gap-1" lang="en">
                {defaultValue || <span className="text-tertiary font-normal">No description</span>}
                <ButtonPrimitive iconOnly onClick={() => setLocalIsEditing(true)} className="inline-block" size="xs">
                    <IconPencil />
                </ButtonPrimitive>
            </p>
        </LemonField.Pure>
    )
}
