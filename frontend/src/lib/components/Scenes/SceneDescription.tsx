import { IconCheck, IconX } from '@posthog/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'
import { SceneInputProps } from './utils'

type SceneDescriptionProps = SceneInputProps

export function SceneDescription({
    defaultValue,
    onSave,
    dataAttrKey,
    optional = false,
    canEdit = true,
}: SceneDescriptionProps): JSX.Element {
    const [localValue, setLocalValue] = useState(defaultValue)
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [hasChanged, setHasChanged] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave(localValue)
        setHasChanged(false)
        setLocalIsEditing(false)
    }

    useEffect(() => {
        setHasChanged(localValue !== defaultValue)
        if (localValue.length === 0 && !optional) {
            setError('Description is required')
        } else {
            setError(null)
        }
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
                    placeholder={optional ? 'Description (optional)' : 'Description'}
                    id="page-description-input"
                    data-attr={`${dataAttrKey}-description-input`}
                    autoFocus
                    error={!!error}
                    className="-ml-1.5"
                />
            </div>
            <div className="flex gap-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged || !!error}
                    tooltip={hasChanged ? 'Update description' : 'No changes to update'}
                    data-attr={`${dataAttrKey}-description-update-button`}
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
                    tooltip={canEdit ? 'Edit description' : 'Description is read-only'}
                    autoHeight
                    menuItem
                    inert={!canEdit}
                >
                    {defaultValue !== '' ? (
                        defaultValue
                    ) : (
                        <span className="text-tertiary font-normal">No description {optional ? '(optional)' : ''}</span>
                    )}
                </ButtonPrimitive>
            </div>
        </div>
    )
}
