import { useEffect, useState } from 'react'

import { IconDocument } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextInputPrimitive } from 'lib/ui/TextInputPrimitive/TextInputPrimitive'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

import { fileSystemTypes } from '~/products'
import { FileSystemIconColor } from '~/types'

import { ProductIconWrapper, iconForType } from '../../panel-layout/ProjectTree/defaultTree'

type ResourceType = {
    to?: string
    tooltip?: string
    /** example: 'action' */
    type: keyof typeof fileSystemTypes | string
    /** example: 'actions' */
    typePlural: string
    /** If your resource type matches a product in fileSystemTypes, you can use this to override the icon */
    forceIcon?: JSX.Element
    /** If your resource type matches a product in fileSystemTypes, you can use this to override the product's icon color */
    forceIconColorOverride?: FileSystemIconColor
}

type SceneMainTitleProps = {
    name?: string
    /**
     * null to hide the description,
     * undefined to show the default description
     */
    description?: string | null
    resourceType: ResourceType
    markdown?: boolean
    isLoading?: boolean
    onNameBlur?: (value: string) => void
    onDescriptionBlur?: (value: string) => void
    docsURL?: string
    canEdit?: boolean
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
    canEdit = false,
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
        <div className="@container/scene-title-section">
            <div className="scene-title-section w-full flex gap-3 group/colorful-product-icons colorful-product-icons-true">
                <div className="flex flex-col gap-1 flex-1">
                    <div className="flex gap-3 [&_svg]:size-6 items-center w-full">
                        <span
                            className={buttonPrimitiveVariants({
                                size: 'base',
                                iconOnly: true,
                                className: 'rounded-sm h-[var(--button-height-lg)]',
                                inert: true,
                            })}
                            aria-hidden
                        >
                            {icon}
                        </span>
                        <SceneName name={name} isLoading={isLoading} onBlur={onNameBlur} canEdit={canEdit} />
                    </div>
                    {description !== null && (description || canEdit) && (
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
                                canEdit={canEdit}
                            />
                        </div>
                    )}
                </div>
                {docsURL && (
                    <>
                        <Link
                            to={`${docsURL}?utm_medium=in-product&utm_campaign=scene-title-section-docs-link`}
                            buttonProps={{ variant: 'panel', className: 'rounded-sm' }}
                            tooltip={`View docs for ${resourceType.typePlural}`}
                            className="hidden @lg:block"
                        >
                            <IconDocument /> Read the docs
                        </Link>
                        <Link
                            to={`${docsURL}?utm_medium=in-product&utm_campaign=scene-title-section-docs-link`}
                            buttonProps={{ variant: 'panel', className: 'rounded-sm', size: 'lg' }}
                            tooltip={`View docs for ${resourceType.typePlural}`}
                            className="@lg:hidden"
                        >
                            <IconDocument />
                        </Link>
                    </>
                )}
            </div>
        </div>
    )
}

type SceneNameProps = {
    name?: string
    isLoading?: boolean
    onBlur?: (value: string) => void
    canEdit?: boolean
}

function SceneName({ name: initialName, isLoading = false, onBlur, canEdit = false }: SceneNameProps): JSX.Element {
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
    const Element =
        onBlur && canEdit ? (
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
    canEdit?: boolean
}

function SceneDescription({
    description: initialDescription,
    markdown = false,
    isLoading = false,
    onBlur,
    canEdit = false,
}: SceneDescriptionProps): JSX.Element | null {
    const [description, setDescription] = useState(initialDescription)

    const textClasses = 'text-sm my-0 select-auto'

    const emptyText = canEdit ? 'Enter description (optional)' : 'No description'

    useEffect(() => {
        if (!isLoading) {
            setDescription(initialDescription)
        }
    }, [initialDescription, isLoading])

    if (!onBlur && canEdit) {
        console.warn('SceneDescription: onBlur is required when canEdit is true')
    }

    const Element =
        onBlur && canEdit ? (
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
                placeholder={emptyText}
            />
        ) : (
            <>
                {markdown && description !== null && description !== undefined ? (
                    <LemonMarkdown
                        lowKeyHeadings
                        className={buttonPrimitiveVariants({
                            inert: true,
                            className: `${textClasses} block`,
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
                        {description !== null ? description : <span className="text-tertiary">{emptyText}</span>}
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
