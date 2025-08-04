import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'
import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'
import { SceneLoadingSkeleton } from './SceneLoadingSkeleton'
import { SceneInputProps, SceneSaveCancelButtons } from './utils'

type SceneNameProps = SceneInputProps

export function SceneName({
    defaultValue = '',
    onSave,
    dataAttrKey,
    optional = false,
    canEdit = true,
    isLoading = false,
}: SceneNameProps): JSX.Element {
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
            setError('Name is required')
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
        <form onSubmit={handleSubmit} name="page-name-form" className="flex flex-col gap-1">
            <ScenePanelLabel htmlFor="page-name-input" title="Name">
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder={`Name ${optional ? '(optional)' : ''}`}
                    id="page-name-input"
                    data-attr={`${dataAttrKey}-name-input`}
                    autoFocus
                    error={!!error}
                />
            </ScenePanelLabel>

            <SceneSaveCancelButtons
                name="name"
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
        <ScenePanelLabel title="Name">
            <ButtonPrimitive
                className="hyphens-auto flex gap-1 items-center"
                lang="en"
                onClick={() => setLocalIsEditing(true)}
                tooltip={canEdit ? 'Edit name' : 'Name is read-only'}
                autoHeight
                menuItem
                inert={!canEdit}
            >
                {localValue !== '' ? (
                    localValue
                ) : (
                    <span className="text-tertiary font-normal">No name {optional ? '(optional)' : ''}</span>
                )}
            </ButtonPrimitive>
        </ScenePanelLabel>
    )
}
