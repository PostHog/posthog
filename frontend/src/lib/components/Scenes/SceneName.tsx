import { IconCheck, IconPencil, IconX } from '@posthog/icons'
import { useValues } from 'kea'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { useEffect, useState } from 'react'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'

type SceneNameProps = {
    defaultValue: string
    onSave: (value: string) => void
    dataAttr?: string
}

export function SceneName({ defaultValue, onSave, dataAttr }: SceneNameProps): JSX.Element {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const lastBreadcrumb = breadcrumbs[breadcrumbs.length - 1]
    const value = typeof lastBreadcrumb?.name === 'string' ? (lastBreadcrumb.name as string) : defaultValue
    const [localValue, setLocalValue] = useState(value)
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
            <div className="gap-0">
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
                />
            </div>
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
        <div className="gap-0">
            <Label intent="menu">Name</Label>
            <p className="m-0 hyphens-auto flex gap-1 items-center" lang="en">
                {value || <span className="text-tertiary font-normal">No name</span>}
                <ButtonPrimitive
                    iconOnly
                    onClick={() => setLocalIsEditing(true)}
                    className="inline-block ml-1"
                    size="sm"
                >
                    <IconPencil />
                </ButtonPrimitive>
            </p>
        </div>
    )
}
