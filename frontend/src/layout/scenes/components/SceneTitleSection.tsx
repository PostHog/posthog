import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconEllipsis, IconPencil, IconX } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb, FileSystemIconColor } from '~/types'

import '../../panel-layout/ProjectTree/defaultTree'
import { ProductIconWrapper, iconForType } from '../../panel-layout/ProjectTree/defaultTree'
import { sceneLayoutLogic } from '../sceneLayoutLogic'
import { SceneBreadcrumbBackButton } from './SceneBreadcrumbs'
import { SceneDivider } from './SceneDivider'

function SceneTitlePanelButton(): JSX.Element | null {
    const { scenePanelOpen, scenePanelIsPresent, scenePanelIsRelative, forceScenePanelClosedWhenRelative } =
        useValues(sceneLayoutLogic)
    const { setScenePanelOpen, setForceScenePanelClosedWhenRelative } = useActions(sceneLayoutLogic)

    if (!scenePanelIsPresent) {
        return null
    }

    return (
        <LemonButton
            onClick={() =>
                scenePanelIsRelative
                    ? setForceScenePanelClosedWhenRelative(!forceScenePanelClosedWhenRelative)
                    : setScenePanelOpen(!scenePanelOpen)
            }
            icon={!scenePanelOpen ? <IconEllipsis className="text-primary" /> : <IconX className="text-primary" />}
            tooltip={
                !scenePanelOpen
                    ? 'Open Info & actions panel'
                    : scenePanelIsRelative
                      ? 'Force close Info & actions panel'
                      : 'Close Info & actions panel'
            }
            data-attr="info-actions-panel"
            aria-label={
                !scenePanelOpen
                    ? 'Open Info & actions panel'
                    : scenePanelIsRelative
                      ? 'Force close Info & actions panel'
                      : 'Close Info & actions panel'
            }
            active={scenePanelOpen}
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
     * @default 0
     */
    renameDebounceMs?: number
    /**
     * If true, saves only on blur (when leaving the field)
     * If false, saves on every change (debounced).
     *
     * Note: It's probably a good idea to set renameDebounceMs > 1000 if this is false
     * @default true
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
    renameDebounceMs = 0,
    saveOnBlur = true,
    noBorder = false,
    actions,
    forceBackTo,
}: SceneMainTitleProps): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const willShowBreadcrumbs = forceBackTo || breadcrumbs.length > 2
    const [isScrolled, setIsScrolled] = useState(false)
    const [nameIsEditing, setNameIsEditing] = useState(false)

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
    return (
        <>
            {/* Description is not sticky, therefor, if there is description, we render a line after scroll  */}
            {effectiveDescription != null && (
                // When this element touches top of the scene, we set the sticky bar to be sticky
                <div
                    data-sticky-sentinel
                    className="scene-title-section-wrapper-sticky-sentinel h-px w-px pointer-events-none absolute top-[-55px]"
                    aria-hidden
                />
            )}

            <div
                className={cn(
                    'scene-title-section-wrapper bg-primary @2xl/main-content:sticky top-[var(--scene-layout-header-height)] z-30 -mx-4 px-4 -mt-4 border-b border-transparent transition-border duration-300',
                    noBorder ? '' : 'border-b border-transparent transition-border',
                    isScrolled && '@2xl/main-content:border-primary [body.storybook-test-runner_&]:border-transparent'
                )}
            >
                <div
                    className={cn(
                        // Name z-indexed behind description initially
                        'scene-title-section flex-1 flex flex-col @2xl/main-content:flex-row gap-2 lg:gap-3 group/colorful-product-icons colorful-product-icons-true lg:items-start group py-2 z-20',
                        {
                            // If scrolled or name is editing, bring to front
                            'z-50': isScrolled || nameIsEditing,
                        }
                    )}
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
                                    handleIsEditingChange={(isEditing) => {
                                        setNameIsEditing(isEditing)
                                    }}
                                />
                            </>
                        )}
                    </div>
                    {actions && (
                        <div className="flex gap-1.5 justify-end items-end @2xl/main-content:items-start @max-2xl:order-first">
                            {actions}
                            <SceneTitlePanelButton />
                        </div>
                    )}
                </div>
                {effectiveDescription == null && !noBorder && <SceneDivider />}
            </div>
            {effectiveDescription != null && (effectiveDescription || canEdit) && (
                // Description z-indexed ahead of name initially
                <div
                    className={cn('[&_svg]:size-6 z-30 -mt-4', {
                        // If scrolled or name is editing, bring to back
                        'z-auto': isScrolled || nameIsEditing,
                    })}
                >
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
    handleIsEditingChange?: (isEditing: boolean) => void
}

function SceneName({
    name: initialName,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 0,
    saveOnBlur = true,
    handleIsEditingChange,
}: SceneNameProps): JSX.Element {
    const [name, setName] = useState(initialName)
    const [isEditing, setIsEditing] = useState(forceEdit)
    const [isNameMultiline, setIsNameMultiline] = useState(false)
    const lastHeightRef = useRef<number>(0)
    const updateTimeoutRef = useRef<number | null>(null)

    const readOnly = !canEdit || !onChange

    const textClasses =
        'text-lg font-semibold my-0 pl-[var(--button-padding-x-sm)] min-h-[var(--button-height-sm)] leading-[1.4]'

    // Handle the height change of the textarea to determine if the name is multiline
    // We do this so we add a shadow to the name when it is multiline instead of it floating above the description with just a border
    const handleHeightChange = useCallback((height: number): void => {
        // Avoid processing the same height multiple times
        if (lastHeightRef.current === height) {
            return
        }
        lastHeightRef.current = height

        // Clear any pending updates
        if (updateTimeoutRef.current) {
            clearTimeout(updateTimeoutRef.current)
        }

        // Defer the state update to avoid synchronous re-renders during layout
        updateTimeoutRef.current = window.setTimeout(() => {
            const shouldBeMultiline = height > 28
            setIsNameMultiline((prev) => (prev !== shouldBeMultiline ? shouldBeMultiline : prev))
            updateTimeoutRef.current = null
        }, 0)
    }, [])

    // Cleanup timeout on unmount to avoid memory leaks
    useEffect(() => {
        return () => {
            if (updateTimeoutRef.current) {
                clearTimeout(updateTimeoutRef.current)
            }
        }
    }, [])

    // If the name is loading, set the name to the initial name
    useEffect(() => {
        if (!isLoading) {
            setName(initialName)
        }
    }, [initialName, isLoading])

    // If the name is forced to be edited, set the editing state to true
    useEffect(() => {
        if (!isLoading && forceEdit) {
            setIsEditing(true)
        } else {
            setIsEditing(false)
        }
    }, [isLoading, forceEdit])

    // Notify parent component that the name is editing
    useEffect(() => {
        handleIsEditingChange?.(isEditing)
    }, [isEditing])

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
    const Element = (
        <>
            {isEditing ? (
                <TextareaPrimitive
                    variant="default"
                    name="name"
                    value={name || ''}
                    onChange={(e) => {
                        if (canEdit) {
                            setName(e.target.value)
                            if (!saveOnBlur) {
                                debouncedOnChange(e.target.value)
                            }
                        }
                    }}
                    data-attr="scene-title-textarea"
                    className={cn(
                        buttonPrimitiveVariants({
                            inert: true,
                            className: `${textClasses} w-full hover:bg-fill-input py-0 pt-px [&_.LemonIcon]:size-4 min-h-[var(--button-height-base)]`,
                            autoHeight: true,
                        }),
                        {
                            // When the textarea is force edit (new item) and multi line to be inline (not absolute)
                            // so the name doesn't overlap over description
                            '@2xl/main-content:absolute @2xl/main-content:inset-0':
                                (forceEdit && !isNameMultiline) || (isEditing && !forceEdit),
                            shadow: isEditing && !forceEdit && isNameMultiline,
                        }
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
                    readOnly={readOnly}
                    onHeightChange={handleHeightChange}
                />
            ) : (
                <Tooltip
                    title={readOnly ? undefined : canEdit && !forceEdit ? 'Click to edit name' : 'Click to view name'}
                    placement="top-start"
                    arrowOffset={10}
                >
                    <ButtonPrimitive
                        className={cn(
                            buttonPrimitiveVariants({ size: 'fit', className: textClasses }),
                            'flex text-left [&_.LemonIcon]:size-4 pl-[var(--button-padding-x-sm)] focus-visible:z-50',
                            {
                                'select-text': readOnly,
                            }
                        )}
                        onClick={() => !readOnly && setIsEditing(true)}
                        fullWidth
                        truncate
                        inert={readOnly}
                        role="heading"
                        aria-level={1}
                    >
                        <span className="truncate">{name || <span className="text-tertiary">Unnamed</span>}</span>
                        {canEdit && !forceEdit && <IconPencil />}
                    </ButtonPrimitive>
                </Tooltip>
            )}
        </>
    )

    if (isLoading) {
        return (
            <div className="w-full flex-1 focus-within:z-50">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div
            className={cn(
                'scene-name flex-1 min-h-[var(--button-height-base)] -ml-[var(--button-padding-x-sm)] @2xl/main-content:ml-0',
                {
                    truncate: !isEditing,
                }
            )}
        >
            {Element}
        </div>
    )
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
    readOnly?: boolean
}

function SceneDescription({
    description: initialDescription,
    markdown = false,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 0,
    saveOnBlur = true,
    readOnly = false,
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
                {isEditing && !readOnly ? (
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
                            '[&_.LemonIcon]:size-4'
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
                            onClick={() => !readOnly && setIsEditing(true)}
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
        <div className="scene-description relative focus-within:z-50">
            <div className="-mx-[var(--button-padding-x-sm)] pb-2 flex items-center gap-0">{Element}</div>
        </div>
    )
}
