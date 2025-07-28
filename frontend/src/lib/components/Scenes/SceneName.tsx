import { IconCheck, IconX } from '@posthog/icons'
import { useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { SceneInputProps } from './utils'

type SceneNameProps = SceneInputProps

export function SceneName({
    defaultValue,
    onSave,
    dataAttrKey,
    optional = false,
    canEdit = true,
}: SceneNameProps): JSX.Element {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const value = typeof lastBreadcrumb?.name === 'string' ? (lastBreadcrumb.name as string) : defaultValue
    const [localValue, setLocalValue] = useState(value)
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
    }, [localValue, defaultValue])

    return localIsEditing ? (
        <form onSubmit={handleSubmit} name="page-name-form" className="flex flex-col gap-1">
            <div className="flex flex-col gap-0">
                <Label intent="menu" htmlFor="page-name-input" className="mx-2">
                    Name
                </Label>
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
            </div>
            <div className="flex gap-1">
                <ButtonPrimitive
                    type="submit"
                    variant="outline"
                    disabled={!hasChanged || !!error}
                    tooltip={error || (hasChanged ? 'Update name' : 'No changes to update')}
                    data-attr={`${dataAttrKey}-name-update-button`}
                >
                    <IconCheck />
                </ButtonPrimitive>
                <ButtonPrimitive
                    type="button"
                    variant="outline"
                    onClick={() => {
                        setLocalValue(value)
                        setLocalIsEditing(false)
                    }}
                    tooltip="Cancel"
                >
                    <IconX />
                </ButtonPrimitive>
            </div>
        </form>
    ) : (
        <div className="flex flex-col gap-0">
            <Label intent="menu" className="mx-2">
                Name
            </Label>
            <ButtonPrimitive
                className="hyphens-auto flex gap-1 items-center"
                lang="en"
                onClick={() => setLocalIsEditing(true)}
                tooltip={canEdit ? 'Edit name' : 'Name is read-only'}
                autoHeight
                menuItem
                inert={!canEdit}
            >
                {value !== '' ? (
                    value
                ) : (
                    <span className="text-tertiary font-normal">No name {optional ? '(optional)' : ''}</span>
                )}
            </ButtonPrimitive>
        </div>
    )
}
