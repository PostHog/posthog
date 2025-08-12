import { LemonDivider } from '@posthog/lemon-ui'
import { capitalizeFirstLetter } from 'kea-forms'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { TextInputPrimitive } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { useState } from 'react'

export function SceneContent({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="flex flex-col gap-y-4">{children}</div>
}

export interface SceneBreadcrumb {
    name: string
    url?: string
}

interface SceneSectionProps {
    title: React.ReactNode
    description?: React.ReactNode
    isLoading?: boolean
    children: React.ReactNode
    className?: string
}

export function SceneSection({ title, description, isLoading, children, className }: SceneSectionProps): JSX.Element {
    if (isLoading) {
        return (
            <div className={cn('flex flex-col gap-4', className)}>
                <div className="flex flex-col gap-0">
                    <h2 className="text-xl font-bold my-0 mb-1 max-w-prose">{title}</h2>
                    {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
                </div>
                <WrappingLoadingSkeleton>{children}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div className={cn('flex flex-col gap-4', className)}>
            <div className="flex flex-col gap-0">
                <h2 className="text-xl font-bold my-0 mb-1 max-w-prose">{title}</h2>
                {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
            </div>
            {children}
        </div>
    )
}

type SceneMainTitleProps = {
    name: string
    description: string
    resourceType: string
    markdown?: boolean
}

export function SceneTitleSection({
    name,
    description,
    resourceType,
    markdown = false,
}: SceneMainTitleProps): JSX.Element {
    // const [isEditing, setIsEditing] = useState(false)
    const resourceCapitalized: string | null = resourceType ? capitalizeFirstLetter(resourceType) : null

    return (
        <div className="flex flex-col gap-0">
            {resourceType && <p className="text-sm text-secondary my-0">{resourceCapitalized}</p>}
            {/* <h1 className="text-2xl font-bold my-0 mb-1 max-w-prose">{name}</h1> */}
            <div className="flex flex-col gap-1">
                <SceneName name={name} />
                <SceneDescription description={description} markdown={markdown} />
            </div>
        </div>
    )
}

type SceneNameProps = {
    name: string
}

export function SceneName({ name: initialName }: SceneNameProps): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const [name, setName] = useState(initialName)

    return (
        <div className="max-w-prose flex flex-col gap-0 -ml-[var(--button-padding-x-lg)]">
            {isEditing ? (
                <>
                    <TextInputPrimitive
                        variant="default"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        className="text-3xl font-bold my-0 bg-transparent field-sizing-content w-full"
                        autoFocus
                        onBlur={() => setIsEditing(false)}
                        size="lg"
                    />
                </>
            ) : (
                <ButtonPrimitive
                    variant="default"
                    size="lg"
                    onClick={() => setIsEditing(true)}
                    className="text-3xl font-bold my-0"
                    menuItem
                >
                    {name}
                </ButtonPrimitive>
            )}
        </div>
    )
}

type SceneDescriptionProps = {
    description: string
    markdown?: boolean
}

export function SceneDescription({
    description: initialDescription,
    markdown = false,
}: SceneDescriptionProps): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const [description, setDescription] = useState(initialDescription)

    return (
        <div className="max-w-prose flex flex-col gap-0 -ml-[var(--button-padding-x-lg)]">
            {isEditing ? (
                <>
                    <TextareaPrimitive
                        variant="default"
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                        className="text-sm font-bold my-0 bg-transparent field-sizing-content w-full"
                        autoFocus
                        onBlur={() => setIsEditing(false)}
                        markdown
                    />
                </>
            ) : (
                <ButtonPrimitive
                    variant="default"
                    onClick={() => setIsEditing(true)}
                    className="text-sm font-bold my-0"
                    autoHeight
                    menuItem
                >
                    {markdown ? <LemonMarkdown lowKeyHeadings>{description}</LemonMarkdown> : description}
                </ButtonPrimitive>
            )}
        </div>
    )
}

export function SceneDivider(): JSX.Element {
    return <LemonDivider className="-mx-4" />
}
