import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconDocument, IconPencil } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

import { FileSystemIconType } from '~/queries/schema/schema-general'
import { FileSystemIconColor } from '~/types'

import '../../panel-layout/ProjectTree/defaultTree'
import { ProductIconWrapper, iconForType } from '../../panel-layout/ProjectTree/defaultTree'

type ResourceType = {
    to?: string
    /** example: 'action' */
    type: FileSystemIconType | string
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
    onNameChange?: (value: string) => void
    onDescriptionChange?: (value: string) => void
    docsURL?: string
    /**
     * If true, the name and description will be editable
     */
    canEdit?: boolean
    /**
     * If true, the name and description will be editable even if canEdit is false
     * Usually this is for 'new' resources, or "edit" mode
     */
    forceEdit?: boolean
    /**
     * The number of milliseconds to debounce the name and description changes
     * useful for renaming resources that update too fast
     * e.g. insights are renamed too fast, so we need to debounce it with 1000ms
     * @default 100
     */
    renameDebounceMs?: number
}

export function SceneTitleSection({
    name,
    description,
    resourceType,
    markdown = false,
    isLoading = false,
    onNameChange,
    onDescriptionChange,
    docsURL,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs,
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
        iconForType(resourceType.type ? (resourceType.type as FileSystemIconType) : undefined)
    )
    return (
        <div className="@container/scene-title-section">
            <div className="scene-title-section w-full flex gap-3 group/colorful-product-icons colorful-product-icons-true">
                <div className="flex flex-col gap-1 flex-1 -ml-[var(--button-padding-x-sm)]">
                    <div className="flex gap-2 [&_svg]:size-6 items-center w-full">
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
                        <SceneName
                            name={name}
                            isLoading={isLoading}
                            onChange={onNameChange}
                            canEdit={canEdit}
                            forceEdit={forceEdit}
                            renameDebounceMs={renameDebounceMs}
                        />
                    </div>
                    {description !== null && (description || canEdit) && (
                        <div className="flex gap-2 [&_svg]:size-6 items-center">
                            <SceneDescription
                                description={description}
                                markdown={markdown}
                                isLoading={isLoading}
                                onChange={onDescriptionChange}
                                canEdit={canEdit}
                                forceEdit={forceEdit}
                                renameDebounceMs={renameDebounceMs}
                            />
                        </div>
                    )}
                </div>
                {docsURL && (
                    <>
                        <Link
                            to={`${docsURL}?utm_medium=in-product&utm_campaign=scene-title-section-docs-link`}
                            buttonProps={{ variant: 'panel', className: 'rounded-sm' }}
                            tooltip={`View docs for ${resourceType.type}`}
                            className="hidden @lg:block"
                        >
                            <IconDocument /> Read the docs
                        </Link>
                        <Link
                            to={`${docsURL}?utm_medium=in-product&utm_campaign=scene-title-section-docs-link`}
                            buttonProps={{ variant: 'panel', className: 'rounded-sm', size: 'lg' }}
                            tooltip={`View docs for ${resourceType.type}`}
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
    onChange?: (value: string) => void
    canEdit?: boolean
    forceEdit?: boolean
    renameDebounceMs?: number
}

function SceneName({
    name: initialName,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 100,
}: SceneNameProps): JSX.Element {
    const [name, setName] = useState(initialName)
    const [isEditing, setIsEditing] = useState(forceEdit)

    const textClasses =
        'text-xl font-semibold my-0 pl-[var(--button-padding-x-sm)] min-h-[var(--button-height-base)] leading-[1.4] select-auto'

    useEffect(() => {
        if (!isLoading) {
            setName(initialName)
        }
    }, [initialName, isLoading])

    useEffect(() => {
        if (!isLoading && forceEdit) {
            setIsEditing(true)
        } else {
            setIsEditing(false)
        }
    }, [isLoading, forceEdit])

    const debouncedOnChange = useDebouncedCallback(onChange || (() => {}), renameDebounceMs)

    // If onBlur is provided, we want to show a button that allows the user to edit the name
    // Otherwise, we want to show the name as a text
    const Element =
        onChange && canEdit ? (
            <>
                {isEditing ? (
                    <TextareaPrimitive
                        variant="default"
                        name="name"
                        value={name || ''}
                        onChange={(e) => {
                            setName(e.target.value)
                            debouncedOnChange(e.target.value)
                        }}
                        className={cn(
                            buttonPrimitiveVariants({
                                inert: true,
                                className: `${textClasses} field-sizing-content w-full hover:bg-fill-input`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4'
                        )}
                        placeholder="Enter name"
                        onBlur={() => !forceEdit && setIsEditing(false)}
                        autoFocus={!forceEdit}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                                e.preventDefault()
                            }
                        }}
                    />
                ) : (
                    <Tooltip
                        title={canEdit && !forceEdit ? 'Edit name' : undefined}
                        placement="top-start"
                        arrowOffset={10}
                    >
                        <ButtonPrimitive
                            className={cn(
                                buttonPrimitiveVariants({ size: 'fit', className: textClasses }),
                                'flex text-left [&_.LemonIcon]:size-4 h-auto'
                            )}
                            onClick={() => setIsEditing(true)}
                            fullWidth
                        >
                            {name || <span className="text-tertiary">Unnamed</span>}
                            {canEdit && !forceEdit && <IconPencil />}
                        </ButtonPrimitive>
                    </Tooltip>
                )}
            </>
        ) : (
            <h1 className={cn(buttonPrimitiveVariants({ size: 'lg', inert: true, className: textClasses }))}>
                {name || <span className="text-tertiary">Unnamed</span>}
            </h1>
        )

    if (isLoading) {
        return (
            <div className="w-full flex-1">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return <div className="scene-name flex flex-col gap-0 flex-1">{Element}</div>
}

type SceneDescriptionProps = {
    description?: string | null
    markdown?: boolean
    isLoading?: boolean
    onChange?: (value: string) => void
    canEdit?: boolean
    forceEdit?: boolean
    renameDebounceMs?: number
}

function SceneDescription({
    description: initialDescription,
    markdown = false,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 100,
}: SceneDescriptionProps): JSX.Element | null {
    const [description, setDescription] = useState(initialDescription)
    const [isEditing, setIsEditing] = useState(forceEdit)

    const textClasses = 'text-sm my-0 select-auto'

    const emptyText = canEdit ? 'Enter description (optional)' : 'No description'

    useEffect(() => {
        if (!isLoading) {
            setDescription(initialDescription)
        }
    }, [initialDescription, isLoading])

    useEffect(() => {
        if (!isLoading && forceEdit) {
            setIsEditing(true)
        } else {
            setIsEditing(false)
        }
    }, [isLoading, forceEdit])

    const debouncedOnDescriptionChange = useDebouncedCallback(onChange || (() => {}), renameDebounceMs)

    const Element =
        onChange && canEdit ? (
            <>
                {isEditing ? (
                    <TextareaPrimitive
                        variant="default"
                        name="description"
                        value={description || ''}
                        onChange={(e) => {
                            setDescription(e.target.value)
                            debouncedOnDescriptionChange(e.target.value)
                        }}
                        className={cn(
                            buttonPrimitiveVariants({
                                inert: true,
                                className: `${textClasses} field-sizing-content w-full hover:bg-fill-input`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4'
                        )}
                        markdown
                        placeholder={emptyText}
                        onBlur={() => !forceEdit && setIsEditing(false)}
                        autoFocus={!forceEdit}
                    />
                ) : (
                    <Tooltip
                        title={canEdit && !forceEdit ? 'Edit description' : undefined}
                        placement="top-start"
                        arrowOffset={10}
                    >
                        <ButtonPrimitive
                            onClick={() => setIsEditing(true)}
                            className="flex text-start px-[var(--button-padding-x-base)] py-[var(--button-padding-y-base)] [&_.LemonIcon]:size-4"
                            autoHeight
                            fullWidth
                            size="base"
                        >
                            <LemonMarkdown lowKeyHeadings>
                                {description || (canEdit ? 'Enter description (optional)' : 'No description')}
                            </LemonMarkdown>
                            {canEdit && !forceEdit && <IconPencil />}
                        </ButtonPrimitive>
                    </Tooltip>
                )}
            </>
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
            <div className="w-full">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return <div className="scene-description flex flex-col gap-0 flex-1">{Element}</div>
}
