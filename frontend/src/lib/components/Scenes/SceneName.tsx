import { IconCheck, IconX } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { cn } from 'lib/utils/css-classes'
import { useEffect, useState } from 'react'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'

type SceneNameProps = {
    defaultValue: string
    onSave?: (value: string) => void
    dataAttr?: string
    forceLocalEditing?: boolean
}

export function SceneName({ defaultValue, onSave, dataAttr, forceLocalEditing = false }:SceneNameProps): JSX.Element {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const value = typeof lastBreadcrumb?.name === 'string' ? (lastBreadcrumb.name as string) : defaultValue
    const [localValue, setLocalValue] = useState(value)
    const [localIsEditing, setLocalIsEditing] = useState(forceLocalEditing)
    const [hasChanged, setHasChanged] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)

    const handleSubmit = (e: React.FormEvent<HTMLFormElement>): void => {
        e.preventDefault()
        onSave?.(localValue)
        setHasChanged(false)
        setLocalIsEditing(false)
    }

    useEffect(() => {
        setHasChanged(localValue !== defaultValue)
        if (localValue.length === 0) {
            setError('Name is required')
        } else {
            setError(null)
        }
    }, [localValue, defaultValue])

    useEffect(() => {
        if (forceLocalEditing) {
            setScenePanelOpen(true)
            setLocalIsEditing(true)
        }
    }, [forceLocalEditing])

    return localIsEditing && onSave ? (
        <form onSubmit={handleSubmit} name="page-name-form" className="flex flex-col gap-1">
            <div className="flex flex-col gap-0">
                <Label intent="menu" htmlFor="page-name-input">
                    Name
                </Label>
                <TextareaPrimitive
                    value={localValue}
                    onChange={(e) => {
                        setLocalValue(e.target.value)
                    }}
                    placeholder="Name (required)"
                    id="page-name-input"
                    data-attr={`${dataAttr}-name-input`}
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
                    tooltip={error || (hasChanged ? 'Update name' : 'No changes to update')}
                    data-attr={`${dataAttr}-name-update-button`}
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
            <Label intent="menu">Name</Label>
            <div className="-ml-1.5">
                <ButtonPrimitive
                    className={cn("hyphens-auto flex gap-1 items-center")}
                    lang="en"
                    onClick={() => setLocalIsEditing(true)}
                    tooltip={onSave ? "Edit name" : "Name is read-only"}
                    autoHeight
                    menuItem
                    inert={!onSave}
                >
                    {value || <span className="text-tertiary font-normal">No name</span>}
                </ButtonPrimitive>
            </div>
        </div>
    )
}
