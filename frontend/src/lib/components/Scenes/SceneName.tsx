import { IconCheck, IconUndo } from '@posthog/icons'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimtive/TextareaPrimitive'
import { useEffect, useState } from 'react'

type SceneNameProps = {
    defaultValue: string
    isEditing: boolean
    onSave: (value: string) => void
    dataAttr?: string
}

export function SceneName({ defaultValue, isEditing, onSave, dataAttr }: SceneNameProps): JSX.Element {
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
        <form onSubmit={handleSubmit} name="page-name-form" className="flex flex-col gap-2 relative">
            <LemonField.Pure label="Name" className="gap-0" htmlFor="page-name-input">
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder="Name (required)"
                    id="page-name-input"
                    data-attr={`${dataAttr}-name-input`}
                    className="pb-10" // Make room for the buttons hugging the bottom of the textarea
                />
            </LemonField.Pure>
            <div className="flex gap-1 absolute right-1 bottom-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update name' : 'No changes to update'}
                    data-attr={`${dataAttr}-name-update-button`}
                >
                    <IconCheck />
                </ButtonPrimitive>
                {hasChanged && (
                    <ButtonPrimitive
                        type="button"
                        variant="outline"
                        disabled={!hasChanged}
                        onClick={() => setLocalValue(defaultValue)}
                        tooltip="Undo name changes"
                    >
                        <IconUndo />
                    </ButtonPrimitive>
                )}
            </div>
        </form>
    ) : (
        <LemonField.Pure label="Name" className="gap-0">
            <p className="m-0 hyphens-auto" lang="en">
                {defaultValue || <span className="text-tertiary font-normal">No name</span>}
            </p>
        </LemonField.Pure>
    )
}
