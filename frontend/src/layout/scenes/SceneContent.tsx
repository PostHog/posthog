import { useEffect, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { LemonDivider, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextInputPrimitive } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

import { fileSystemTypes } from '~/products'
import { FileSystemIconColor } from '~/types'

import { ProductIconWrapper, iconForType } from '../panel-layout/ProjectTree/defaultTree'

export function SceneContent({
    children,
    className,
    forceNewSpacing,
}: {
    children: React.ReactNode
    className?: string
    forceNewSpacing?: boolean
}): JSX.Element {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    return (
        <div className={cn('scene-content flex flex-col', (newSceneLayout || forceNewSpacing) && 'gap-y-4', className)}>
            {children}
        </div>
    )
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
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    // If not in new scene layout, we don't want to show anything new
    if (!newSceneLayout) {
        return (
            <div className={cn('scene-section--fallback flex flex-col gap-y-4', className)}>
                {!hideTitleAndDescription && (
                    <div className="flex flex-col gap-y-0">
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
            <div className={cn('flex flex-col gap-y-4', className)}>
                <div className="flex flex-col gap-y-0">
                    <h2 className="text-base font-semibold my-0 mb-1 max-w-prose">{title}</h2>
                    {description && <p className="text-sm text-secondary my-0 max-w-prose">{description}</p>}
                </div>
                <WrappingLoadingSkeleton>{children}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div className={cn('scene-section--new-layout flex flex-col gap-y-4', className)}>
            <div className="flex flex-col gap-y-0">
                <h2 className="text-base font-semibold my-0 mb-1 max-w-prose">{title}</h2>
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
    // If your resource type matches a product in fileSystemTypes, you can use this to override the icon
    forceIcon?: JSX.Element
    // If your resource type matches a product in fileSystemTypes, you can use this to override the product's icon color
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
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

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
            <div className="flex flex-col gap-1 flex-1">
                <div className="flex gap-3 [&_svg]:size-6 items-center w-full">
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
                    <SceneName name={name} isLoading={isLoading} onBlur={onNameBlur} />
                </div>
                {description && (
                    <div className="flex gap-3 [&_svg]:size-6 items-center">
                        <span
                            className={buttonPrimitiveVariants({
                                size: 'base',
                                iconOnly: true,
                                inert: true,
                            })}
                            aria-hidden
                        />
                        <SceneDescription
                            description={description}
                            markdown={markdown}
                            isLoading={isLoading}
                            onBlur={onDescriptionBlur}
                        />
                    </div>
                )}
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
    const [name, setName] = useState(initialName)

    const textClasses =
        'text-2xl font-semibold my-0 pl-[var(--button-padding-x-sm)] h-[var(--button-height-lg)] leading-[1.4] select-auto'

    useEffect(() => {
        if (!isLoading) {
            setName(initialName)
        }
    }, [initialName, isLoading])

    // If onBlur is provided, we want to show a button that allows the user to edit the name
    // Otherwise, we want to show the name as a text
    const Element = onBlur ? (
        <TextInputPrimitive
            variant="default"
            value={name || ''}
            onChange={(e) => setName(e.target.value)}
            className={`${textClasses} field-sizing-content w-full`}
            onBlur={() => {
                if (initialName !== name) {
                    onBlur?.(name || '')
                }
            }}
            size="lg"
        />
    ) : (
        <h1 className={cn(buttonPrimitiveVariants({ size: 'lg', inert: true, className: textClasses }))}>
            {name || <span className="text-tertiary">Unnamed</span>}
        </h1>
    )

    if (isLoading) {
        return (
            <div className="max-w-prose w-full flex-1">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return <div className="scene-name max-w-prose flex flex-col gap-0 flex-1">{Element}</div>
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
}: SceneDescriptionProps): JSX.Element | null {
    const [description, setDescription] = useState(initialDescription)

    const textClasses = 'text-sm my-0 select-auto'

    useEffect(() => {
        if (!isLoading) {
            setDescription(initialDescription)
        }
    }, [initialDescription, isLoading])

    const Element = onBlur ? (
        <TextareaPrimitive
            variant="default"
            value={description || ''}
            onChange={(e) => setDescription(e.target.value)}
            className={`${textClasses} field-sizing-content w-full`}
            onBlur={() => {
                if (initialDescription !== description) {
                    onBlur?.(description || '')
                }
            }}
            markdown
        />
    ) : (
        <>
            {markdown && description ? (
                <LemonMarkdown
                    lowKeyHeadings
                    className={buttonPrimitiveVariants({
                        inert: true,
                        className: `${textClasses}`,
                        autoHeight: true,
                    })}
                >
                    {description}
                </LemonMarkdown>
            ) : (
                <p
                    className={buttonPrimitiveVariants({
                        inert: true,
                        className: `${textClasses}`,
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
            <div className="max-w-prose w-full">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return <div className="scene-description max-w-prose flex flex-col gap-0 flex-1">{Element}</div>
}

export function SceneDivider(): JSX.Element | null {
    const newSceneLayout = useFeatureFlag('NEW_SCENE_LAYOUT')

    // If not in new scene layout, we don't want to show anything new
    if (!newSceneLayout) {
        return null
    }

    return <LemonDivider className="scene-divider -mx-4 w-[calc(100%+var(--spacing)*8)]" />
}
