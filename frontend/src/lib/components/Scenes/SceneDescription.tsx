import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { SceneLoadingSkeleton } from './SceneLoadingSkeleton'
import { SceneInputProps, SceneSaveCancelButtons } from './utils'

type SceneDescriptionProps = SceneInputProps

export function SceneDescription({
    defaultValue,
    onSave,
    dataAttrKey,
    optional = false,
    canEdit = true,
    isLoading = false,
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
    }, [localValue, defaultValue, optional])

    useEffect(() => {
        if (!isLoading && !localIsEditing) {
            setLocalValue(defaultValue)
        }
    }, [isLoading, defaultValue, localIsEditing])

    if (isLoading) {
        return <SceneLoadingSkeleton />
    }

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-description-form" className="flex flex-col gap-1">
            <ScenePanelLabel htmlFor="page-description-input" title="Description">
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
                />
            </ScenePanelLabel>

            <SceneSaveCancelButtons
                name="description"
                onCancel={() => {
                    setLocalValue(defaultValue)
                    setLocalIsEditing(false)
                }}
                hasChanged={hasChanged}
                error={error}
                dataAttrKey={dataAttrKey}
                isLoading={isLoading}
            />
        </form>
    ) : (
        <ScenePanelLabel title="Description">
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
        </ScenePanelLabel>
    )
}
