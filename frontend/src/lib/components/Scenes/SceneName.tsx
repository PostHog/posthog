import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { LemonField } from 'lib/lemon-ui/LemonField/LemonField'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimtive/TextareaPrimitive'
import { useEffect, useState } from 'react'

type SceneNameProps = {
    defaultValue: string
    onSave: (value: string) => void
    dataAttr?: string
}

export function SceneName({ defaultValue, onSave, dataAttr }: SceneNameProps): JSX.Element {
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
        <form onSubmit={handleSubmit} name="page-name-form" className="flex flex-col gap-1">
            <LemonField.Pure label="Name" className="gap-0" htmlFor="page-name-input">
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder="Name (required)"
                    id="page-name-input"
                    data-attr={`${dataAttr}-name-input`}
                    autoFocus
                />
            </LemonField.Pure>
            <div className="flex gap-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged}
                    tooltip={hasChanged ? 'Update name' : 'No changes to update'}
                    data-attr={`${dataAttr}-name-update-button`}
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
        <LemonField.Pure label="Name" className="gap-0">
            <p className="m-0 hyphens-auto" lang="en">
                {defaultValue || <span className="text-tertiary font-normal">No name</span>}
                <ButtonPrimitive
                    iconOnly
                    onClick={() => setLocalIsEditing(true)}
                    className="inline-block ml-1"
                    size="xs"
                >
                    <IconPencil />
                </ButtonPrimitive>
            </p>
        </LemonField.Pure>
    )
}
