import { useEffect, useState } from 'react'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'

import { ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { SceneLoadingSkeleton } from './SceneLoadingSkeleton'
import { SceneSaveCancelButtons, SceneTextInputProps } from './utils'

export function SceneTextInput({
    defaultValue = '',
    onSave,
    dataAttrKey,
    optional = false,
    canEdit = true,
    isLoading = false,
    name,
}: SceneTextInputProps): JSX.Element {
    const [localValue, setLocalValue] = useState(defaultValue)
    const [localIsEditing, setLocalIsEditing] = useState(false)
    const [hasChanged, setHasChanged] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const nameCapitalized = name.charAt(0).toUpperCase() + name.slice(1)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave(localValue)
        setHasChanged(false)
        setLocalIsEditing(false)
    }

    useEffect(() => {
        setHasChanged(localValue !== defaultValue)
        if (localValue.length === 0 && !optional) {
            setError(`${nameCapitalized} is required`)
        } else {
            setError(null)
        }
    }, [localValue, defaultValue, optional, nameCapitalized])

    useEffect(() => {
        if (!isLoading && !localIsEditing) {
            setLocalValue(defaultValue)
        }
    }, [isLoading, defaultValue, localIsEditing])

    if (isLoading) {
        return <SceneLoadingSkeleton />
    }

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name={`page-${name}-form`} className="flex flex-col gap-1">
            <ScenePanelLabel htmlFor={`page-${name}-input`} title={nameCapitalized}>
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder={`${nameCapitalized} ${optional ? '(optional)' : ''}`}
                    id={`page-${name}-input`}
                    data-attr={`${dataAttrKey}-${name}-input`}
                    autoFocus
                    error={!!error}
                />
            </ScenePanelLabel>

            <SceneSaveCancelButtons
                name={name}
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
        <ScenePanelLabel title={nameCapitalized}>
            <ButtonPrimitive
                className="hyphens-auto flex gap-1 items-center"
                lang="en"
                onClick={() => setLocalIsEditing(true)}
                tooltip={canEdit ? `Edit ${name}` : `${nameCapitalized} is read-only`}
                autoHeight
                menuItem
                inert={!canEdit}
                variant="panel"
            >
                {localValue !== '' ? (
                    localValue
                ) : (
                    <span className="text-tertiary font-normal">
                        No {name} {optional ? '(optional)' : ''}
                    </span>
                )}
            </ButtonPrimitive>
        </ScenePanelLabel>
    )
}
