import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconEllipsis, IconPencil, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb, FileSystemIconColor } from '~/types'

import '../../panel-layout/ProjectTree/defaultTree'
import { ProductIconWrapper, iconForType } from '../../panel-layout/ProjectTree/defaultTree'
import { sceneLayoutLogic } from '../sceneLayoutLogic'
import { SceneBreadcrumbBackButton } from './SceneBreadcrumbs'
import { SceneDivider } from './SceneDivider'

export function SceneTitlePanelButton({ inPanel = false }: { inPanel?: boolean }): JSX.Element | null {
    const { scenePanelOpenManual, scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)

    // Show "Open" button when panel is closed, show "Close" button when panel is open
    // Both should never render simultaneously to avoid Playwright strict mode violations
    if (!scenePanelIsPresent || inPanel !== scenePanelOpenManual) {
        return null
    }

    return (
        <LemonButton
            className={cn(!inPanel && '-mr-2')}
            onClick={() => setScenePanelOpen(!scenePanelOpenManual)}
            icon={inPanel ? <IconX className="text-primary p-0.5" /> : <IconEllipsis className="text-primary" />}
            tooltip={inPanel ? 'Close Info & actions panel' : 'Open Info & actions panel'}
            data-attr="info-actions-panel"
            aria-label={inPanel ? 'Close Info & actions panel' : 'Open Info & actions panel'}
            active={inPanel ? true : scenePanelOpenManual}
            size="small"
        />
    )
}
type ResourceType = {
    to?: string
    /** pass in a value from the FileSystemIconType enum, or a string if not available */
    type: FileSystemIconType | string
    /** If your resource type matches a product in fileSystemTypes, you can use this to override the icon */
    forceIcon?: JSX.Element
    /** If your resource type matches a product in fileSystemTypes and has a color defined, you can use this to override the product's icon color */
    forceIconColorOverride?: FileSystemIconColor
}

type SceneMainTitleProps = {
    /**
     * null to hide the name,
     * undefined to show the default name
     */
    name?: string | null
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
    /**
     * If true, saves only on blur (when leaving the field)
     * If false, saves on every change (debounced) - original behavior.
     *
     * Note: It's probably a good idea to set renameDebounceMs to 0 if this is true
     * @default false
     */
    saveOnBlur?: boolean
    /**
     * If true, removes the border from the title section
     * */
    noBorder?: boolean
    /**
     * If true, the actions from PageHeader will be shown
     * @default false
     */
    actions?: JSX.Element
    /**
     * If provided, the back button will be forced to this breadcrumb
     * @default undefined
     */
    forceBackTo?: Breadcrumb

    /**
     * Additional class name for the title section
     */
    className?: string
}

export function SceneTitleSection({
    name,
    description,
    resourceType,
    markdown = false,
    isLoading = false,
    onNameChange,
    onDescriptionChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs,
    saveOnBlur = false,
    noBorder = false,
    actions,
    forceBackTo,
    className,
}: SceneMainTitleProps): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const { zenMode } = useValues(navigation3000Logic)
    const willShowBreadcrumbs = forceBackTo || breadcrumbs.length > 2
    const [isScrolled, setIsScrolled] = useState(false)

    const effectiveDescription = description

    useEffect(() => {
        const stickyElement = document.querySelector('[data-sticky-sentinel]')
        if (!stickyElement) {
            return
        }

        const observer = new IntersectionObserver(
            ([entry]) => {
                setIsScrolled(!entry.isIntersecting)
            },
            { threshold: 1 }
        )

        observer.observe(stickyElement)
        return () => observer.disconnect()
    }, [])

    const icon = resourceType.forceIcon ? (
        <ProductIconWrapper type={resourceType.type} colorOverride={resourceType.forceIconColorOverride}>
            {resourceType.forceIcon}
        </ProductIconWrapper>
    ) : (
        iconForType(resourceType.type ? (resourceType.type as FileSystemIconType) : undefined)
    )

    if (zenMode) {
        return null
    }

    return (
        <>
            {/* Description is not sticky, therefor, if there is description, we render a line after scroll  */}
            {effectiveDescription != null && (
                // When this element touches top of the scene, we set the sticky bar to be sticky
                <div data-sticky-sentinel className="h-px w-px pointer-events-none absolute -top-4" aria-hidden />
            )}

            <div
                className={cn(
                    'bg-primary @2xl/main-content:sticky -top-[calc(var(--spacing)*4)] z-30 -mx-4 px-4 -mt-4 duration-300',
                    noBorder ? '' : 'border-b border-transparent transition-border',
                    isScrolled && '@2xl/main-content:border-primary [body.storybook-test-runner_&]:border-transparent',
                    className
                )}
            >
                <div
                    className="scene-title-section flex-1 flex flex-col @2xl/main-content:flex-row gap-1 lg:gap-3 group/colorful-product-icons colorful-product-icons-true lg:items-start group py-2"
                    data-editable={canEdit}
                >
                    <div
                        className={cn('flex gap-1 flex-1 min-w-0', {
                            '-ml-[var(--button-padding-x-base)]': willShowBreadcrumbs,
                        })}
                    >
                        {willShowBreadcrumbs && <SceneBreadcrumbBackButton forceBackTo={forceBackTo} />}
                        {name !== null && (
                            <>
                                <span
                                    className={buttonPrimitiveVariants({
                                        size: 'lg',
                                        iconOnly: true,
                                        className:
                                            'hidden @2xl/main-content:flex size-[var(--button-size-base)] max-h-[var(--button-height-base)]',
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
                                    saveOnBlur={saveOnBlur}
                                />
                            </>
                        )}
                    </div>
                    {actions && (
                        <div className="flex gap-1.5 justify-end items-end @2xl/main-content:items-start ml-4 @max-2xl:order-first">
                            {actions}
                            <SceneTitlePanelButton />
                        </div>
                    )}
                </div>
                {effectiveDescription == null && !noBorder && <SceneDivider />}
            </div>
            {effectiveDescription != null && (effectiveDescription || canEdit) && (
                <div className="[&_svg]:size-6">
                    <SceneDescription
                        description={effectiveDescription}
                        markdown={markdown}
                        isLoading={isLoading}
                        onChange={onDescriptionChange}
                        canEdit={canEdit}
                        forceEdit={forceEdit}
                        renameDebounceMs={renameDebounceMs}
                        saveOnBlur={saveOnBlur}
                    />
                    {!noBorder && <SceneDivider />}
                </div>
            )}
        </>
    )
}

type SceneNameProps = {
    name?: string
    isLoading?: boolean
    onChange?: (value: string) => void
    canEdit?: boolean
    forceEdit?: boolean
    renameDebounceMs?: number
    saveOnBlur?: boolean
}

function SceneName({
    name: initialName,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 100,
    saveOnBlur = false,
}: SceneNameProps): JSX.Element {
    const [name, setName] = useState(initialName)
    const [isEditing, setIsEditing] = useState(forceEdit)

    const textClasses =
        'text-xl font-semibold my-0 pl-[var(--button-padding-x-sm)] min-h-[var(--button-height-sm)] leading-[1.4] select-auto'

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

    const debouncedOnBlurSave = useDebouncedCallback((value: string) => {
        if (onChange) {
            onChange(value)
        }
    }, renameDebounceMs)

    const debouncedOnChange = useDebouncedCallback((value: string) => {
        if (onChange) {
            onChange(value)
        }
    }, renameDebounceMs)

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
                            if (!saveOnBlur) {
                                debouncedOnChange(e.target.value)
                            }
                        }}
                        data-attr="scene-title-textarea"
                        className={cn(
                            buttonPrimitiveVariants({
                                inert: true,
                                className: `${textClasses} w-full hover:bg-fill-input py-0`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4 input-like'
                        )}
                        placeholder="Enter name"
                        onBlur={() => {
                            // Save changes when leaving the field (only if saveOnBlur is true)
                            if (saveOnBlur && name !== initialName) {
                                debouncedOnBlurSave(name || '')
                            }
                            // Exit edit mode if not forced
                            if (!forceEdit) {
                                setIsEditing(false)
                            }
                        }}
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
                                'flex text-left [&_.LemonIcon]:size-4 pl-[var(--button-padding-x-sm)] focus-visible:z-50'
                            )}
                            onClick={() => setIsEditing(true)}
                            fullWidth
                            truncate
                        >
                            <span className="truncate">{name || <span className="text-tertiary">Unnamed</span>}</span>
                            {canEdit && !forceEdit && <IconPencil />}
                        </ButtonPrimitive>
                    </Tooltip>
                )}
            </>
        ) : (
            <h1 className={cn(buttonPrimitiveVariants({ size: 'base', inert: true, className: `${textClasses}` }))}>
                <span className="min-w-fit">{name || <span className="text-tertiary">Unnamed</span>}</span>
            </h1>
        )

    if (isLoading) {
        return (
            <div className="w-full flex-1 focus-within:z-50">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return <div className={cn('scene-name flex-1', !isEditing && onChange && canEdit && 'truncate ')}>{Element}</div>
}

type SceneDescriptionProps = {
    description?: string | null
    markdown?: boolean
    isLoading?: boolean
    onChange?: (value: string) => void
    canEdit?: boolean
    forceEdit?: boolean
    renameDebounceMs?: number
    saveOnBlur?: boolean
}

function SceneDescription({
    description: initialDescription,
    markdown = false,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 100,
    saveOnBlur = false,
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

    const debouncedOnBlurSaveDescription = useDebouncedCallback((value: string) => {
        if (onChange) {
            onChange(value)
        }
    }, renameDebounceMs)

    const debouncedOnDescriptionChange = useDebouncedCallback((value: string) => {
        if (onChange) {
            onChange(value)
        }
    }, renameDebounceMs)

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
                            if (!saveOnBlur) {
                                debouncedOnDescriptionChange(e.target.value)
                            }
                        }}
                        data-attr="scene-description-textarea"
                        className={cn(
                            buttonPrimitiveVariants({
                                inert: true,
                                className: `${textClasses} w-full hover:bg-fill-input px-[var(--button-padding-x-sm)]`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4 input-like'
                        )}
                        wrapperClassName="w-full"
                        markdown={markdown}
                        placeholder={emptyText}
                        onBlur={() => {
                            // Save changes when leaving the field (only if saveOnBlur is true)
                            if (saveOnBlur && description !== initialDescription) {
                                debouncedOnBlurSaveDescription(description || '')
                            }
                            // Exit edit mode if not forced
                            if (!forceEdit) {
                                setIsEditing(false)
                            }
                        }}
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
                            className="flex text-start px-[var(--button-padding-x-sm)] py-[var(--button-padding-y-base)] [&_.LemonIcon]:size-4 focus-visible:z-50"
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
                            className: `${textClasses} block px-[var(--button-padding-x-sm)]`,
                            autoHeight: true,
                        })}
                    >
                        {description}
                    </LemonMarkdown>
                ) : (
                    <p
                        className={buttonPrimitiveVariants({
                            inert: true,
                            className: `${textClasses} px-[var(--button-padding-x-sm)]`,
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

    return (
        <div className="scene-description -mt-4 relative focus-within:z-50">
            <div className="-mx-[var(--button-padding-x-sm)] pb-2 flex items-center gap-0">{Element}</div>
        </div>
    )
}
