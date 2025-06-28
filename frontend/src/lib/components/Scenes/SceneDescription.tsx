import { IconCheck, IconUndo } from '@posthog/icons'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimtive/TextareaPrimitive'
import { useEffect, useState } from 'react'

type SceneDescriptionFormProps = {
    defaultValue: string
    isEditing: boolean
    onSave: (value: string) => void
    dataAttr?: string
}

export function SceneDescriptionForm({
    defaultValue,
    isEditing,
    onSave,
    dataAttr,
}: SceneDescriptionFormProps): JSX.Element {
    const [localValue, setLocalValue] = useState(defaultValue)
    const [localIsEditing, setLocalIsEditing] = useState(isEditing)
    const [hasChanged, setHasChanged] = useState(false)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave(localValue)
        setHasChanged(false)
    }

    useEffect(() => {
        setLocalIsEditing(isEditing)
    }, [isEditing])

    useEffect(() => {
        setHasChanged(localValue !== defaultValue)
    }, [localValue, defaultValue])

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-description-form" className="flex flex-col gap-2 relative">
            <LemonField.Pure label="Description" className="gap-0" htmlFor="page-description-input">
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder="Description (optional)"
                    id="page-description-input"
                    data-attr={`${dataAttr}-description-input`}
                    className="pb-10" // Make room for the buttons hugging the bottom of the textarea
                />
            </LemonField.Pure>
            <div className="flex gap-1 absolute right-1 bottom-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update description' : 'No changes to update'}
                    data-attr={`${dataAttr}-description-update-button`}
                >
                    <IconCheck />
                </ButtonPrimitive>
                {hasChanged && (
                    <ButtonPrimitive
                        type="button"
                        variant="outline"
                        disabled={!hasChanged}
                        onClick={() => setLocalValue(defaultValue)}
                        tooltip="Undo description changes"
                    >
                        <IconUndo />
                    </ButtonPrimitive>
                )}
            </div>
        </form>
    ) : (
        <LemonField.Pure label="Description" className="gap-0">
            <p className="m-0 hyphens-auto" lang="en">
                {defaultValue || <span className="text-tertiary font-normal">No description</span>}
            </p>
        </LemonField.Pure>
    )
}
