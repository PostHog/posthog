import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonDivider, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextInputPrimitive } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

import { fileSystemTypes } from '~/products'
import { FileSystemIconColor } from '~/types'

import { ProductIconWrapper, iconForType } from '../panel-layout/ProjectTree/defaultTree'

export function SceneContent({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="scene-content flex flex-col gap-y-4">{children}</div>
}

interface SceneSectionProps {
    title: React.ReactNode
    description?: React.ReactNode
    isLoading?: boolean
    children: React.ReactNode
    className?: string
    hideTitleAndDescription?: boolean
}

export function SceneSection({
    title,
    description,
    isLoading,
    children,
    className,
    hideTitleAndDescription,
}: SceneSectionProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    // If not in new scene layout, we don't want to show anything new
    if (!newSceneLayout) {
        return (
            <div className={cn('scene-section--fallback flex flex-col gap-4', className)}>
                {!hideTitleAndDescription && (
                    <div className="flex flex-col">
                        <h2 className="flex-1 subtitle mt-0">{title}</h2>
                        <p className="m-0">{description}</p>
                    </div>
                )}
                {children}
            </div>
        )
    }

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
        <div className={cn('scene-section--new-layout flex flex-col gap-4', className)}>
            <div className="flex flex-col gap-0">
                <h2 className="text-xl font-bold my-0 mb-1 max-w-prose">{title}</h2>
                {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
            </div>
            {children}
        </div>
    )
}

type ResourceType = {
    to?: string
    tooltip?: string
    // example: 'action'
    type: keyof typeof fileSystemTypes | string
    // example: 'actions'
    typePlural: string
    forceIcon?: JSX.Element
    forceIconColorOverride?: FileSystemIconColor
}
type SceneMainTitleProps = {
    name?: string | null
    description?: string | null
    resourceType: ResourceType
    markdown?: boolean
    isLoading?: boolean
    onNameBlur?: (value: string) => void
    onDescriptionBlur?: (value: string) => void
    docsURL?: string
}

export function SceneTitleSection({
    name,
    description,
    resourceType,
    markdown = false,
    isLoading = false,
    onNameBlur,
    onDescriptionBlur,
    docsURL,
}: SceneMainTitleProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    if (!newSceneLayout) {
        return null
    }

    const icon = resourceType.forceIcon ? (
        <ProductIconWrapper type={resourceType.type} colorOverride={resourceType.forceIconColorOverride}>
            {resourceType.forceIcon}
        </ProductIconWrapper>
    ) : (
        iconForType(resourceType.type)
    )

    return (
        <div className="scene-title-section w-full flex gap-0 group/colorful-product-icons colorful-product-icons-true">
            <div className="flex flex-col gap-1.5 flex-1">
                <div className="flex gap-3 [&_svg]:size-6 items-center">
                    {resourceType.to ? (
                        <Link
                            to={resourceType.to}
                            tooltip={resourceType.tooltip || `View all ${resourceType.typePlural}`}
                            buttonProps={{
                                size: 'base',
                                iconOnly: true,
                                variant: 'panel',
                                className: 'rounded-sm h-[var(--button-height-lg)]',
                            }}
                        >
                            {icon}
                        </Link>
                    ) : (
                        <span
                            className={buttonPrimitiveVariants({
                                size: 'base',
                                iconOnly: true,
                                className: 'rounded-sm h-[var(--button-height-lg)]',
                                inert: true,
                            })}
                        >
                            {icon}
                        </span>
                    )}
                    <SceneName name={name} isLoading={isLoading} onBlur={onNameBlur} />
                </div>
                <SceneDescription
                    description={description}
                    markdown={markdown}
                    isLoading={isLoading}
                    onBlur={onDescriptionBlur}
                />
            </div>
            {docsURL && (
                <Link
                    to={`${docsURL}?utm_medium=in-product&utm_campaign=scene-title-section-docs-link`}
                    buttonProps={{ variant: 'panel', className: 'rounded-sm' }}
                    tooltip={`View docs for ${resourceType.typePlural}`}
                >
                    <IconDocument /> <span className="hidden lg:block">Read the docs</span>
                </Link>
            )}
        </div>
    )
}

type SceneNameProps = {
    name?: string | null
    isLoading?: boolean
    onBlur?: (value: string) => void
}

export function SceneName({ name: initialName, isLoading = false, onBlur }: SceneNameProps): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const [name, setName] = useState(initialName)

    const textClasses =
        'text-3xl font-bold my-0 pl-[var(--button-padding-x-sm)] h-[var(--button-height-lg)] leading-[1.4] select-auto'

    useEffect(() => {
        if (!isLoading) {
            setName(initialName)
        }
    }, [initialName, isLoading])

    // If onBlur is provided, we want to show a button that allows the user to edit the name
    // Otherwise, we want to show the name as a text
    const Element = onBlur ? (
        <ButtonPrimitive
            size="lg"
            onClick={() => setIsEditing(true)}
            className={textClasses}
            menuItem
            variant="panel"
            tooltip={isEditing ? null : 'Edit name'}
        >
            {name || <span className="text-tertiary">Unnamed</span>}
        </ButtonPrimitive>
    ) : (
        <h1 className={cn(buttonPrimitiveVariants({ size: 'lg', inert: true, className: textClasses }))}>
            {name || <span className="text-tertiary">Unnamed</span>}
        </h1>
    )

    if (isLoading) {
        return (
            <div className="max-w-prose">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div className="scene-name max-w-prose flex flex-col gap-0 -ml-[calc(var(--button-padding-x-sm)+2px)]">
            {isEditing ? (
                <>
                    <TextInputPrimitive
                        variant="default"
                        value={name || ''}
                        onChange={(e) => setName(e.target.value)}
                        className={`${textClasses} bg-transparent field-sizing-content w-full`}
                        autoFocus
                        onBlur={() => {
                            setIsEditing(false)
                            if (initialName !== name) {
                                onBlur?.(name || '')
                            }
                        }}
                        size="lg"
                    />
                </>
            ) : (
                Element
            )}
        </div>
    )
}

type SceneDescriptionProps = {
    description?: string | null
    markdown?: boolean
    isLoading?: boolean
    onBlur?: (value: string) => void
}

export function SceneDescription({
    description: initialDescription,
    markdown = false,
    isLoading = false,
    onBlur,
}: SceneDescriptionProps): JSX.Element {
    const [isEditing, setIsEditing] = useState(false)
    const [description, setDescription] = useState(initialDescription)

    const textClasses = 'text-sm my-0 select-auto'

    useEffect(() => {
        if (!isLoading) {
            setDescription(initialDescription)
        }
    }, [initialDescription, isLoading])

    const Element = onBlur ? (
        <ButtonPrimitive
            onClick={() => setIsEditing(true)}
            className={`${textClasses}`}
            autoHeight
            menuItem
            variant="panel"
            tooltip={isEditing ? null : 'Edit description'}
        >
            {markdown && description ? (
                <LemonMarkdown lowKeyHeadings className="[&_p]:my-0 [&_p]:leading-[20px]">
                    {description}
                </LemonMarkdown>
            ) : (
                description || <span className="text-tertiary">No description (optional)</span>
            )}
        </ButtonPrimitive>
    ) : (
        <>
            {markdown && description ? (
                <LemonMarkdown
                    lowKeyHeadings
                    className={buttonPrimitiveVariants({
                        inert: true,
                        className: `${textClasses} -ml-[var(--button-padding-x-base)]`,
                        autoHeight: true,
                    })}
                >
                    {description}
                </LemonMarkdown>
            ) : (
                <p
                    className={buttonPrimitiveVariants({
                        inert: true,
                        className: `${textClasses} -ml-[var(--button-padding-x-base)]`,
                        autoHeight: true,
                    })}
                >
                    {description ? description : <span className="text-tertiary">No description (optional)</span>}
                </p>
            )}
        </>
    )

    if (isLoading) {
        return (
            <div className="max-w-prose">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div className="scene-description max-w-prose flex flex-col gap-0">
            {isEditing ? (
                <>
                    <TextareaPrimitive
                        variant="default"
                        value={description || ''}
                        onChange={(e) => setDescription(e.target.value)}
                        className={`${textClasses} bg-transparent field-sizing-content w-full`}
                        autoFocus
                        onBlur={() => {
                            setIsEditing(false)
                            if (initialDescription !== description) {
                                onBlur?.(description || '')
                            }
                        }}
                        markdown
                    />
                </>
            ) : (
                Element
            )}
        </div>
    )
}

export function SceneDivider(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    // If not in new scene layout, we don't want to show anything new
    if (!newSceneLayout) {
        return null
    }

    return <LemonDivider className="scene-divider -mx-4 w-[calc(100%+var(--spacing)*8)]" />
}
