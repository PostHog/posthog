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

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb, FileSystemIconColor } from '~/types'

import '../../panel-layout/ProjectTree/defaultTree'
import { ProductIconWrapper, iconForType } from '../../panel-layout/ProjectTree/defaultTree'
import { sceneLayoutLogic } from '../sceneLayoutLogic'
import { SceneBreadcrumbBackButton } from './SceneBreadcrumbs'

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
    renameDebounceMs,
    saveOnBlur = false,
    actions,
    forceBackTo,
}: SceneMainTitleProps): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const { sceneLayoutConfig } = useValues(sceneLayoutLogic)
    const willShowBreadcrumbs = forceBackTo || breadcrumbs.length > 2

    const effectiveDescription = description !== undefined ? description : sceneLayoutConfig?.description

    const icon = resourceType.forceIcon ? (
        <ProductIconWrapper type={resourceType.type} colorOverride={resourceType.forceIconColorOverride}>
            {resourceType.forceIcon}
        </ProductIconWrapper>
    ) : (
        iconForType(resourceType.type ? (resourceType.type as FileSystemIconType) : undefined)
    )
    return (
        <div
            className="scene-title-section w-full flex flex-col @2xl/main-content:flex-row gap-3 group/colorful-product-icons colorful-product-icons-true items-start group"
            data-editable={canEdit}
        >
            <div className="w-full flex flex-col flex-1 -ml-[var(--button-padding-x-sm)] group/colorful-product-icons colorful-product-icons-true items-start">
                {/* If we're showing breadcrumbs, we want to show the actions inline with the back button */}
                {willShowBreadcrumbs && (
                    <div className="flex justify-between w-full items-center mb-1">
                        <SceneBreadcrumbBackButton forceBackTo={forceBackTo} />
                        <div className="pt-1 shrink-0">
                            {actions && (
                                <div className="flex gap-2 shrink-0 ml-auto">
                                    {actions}
                                    <SceneTitlePanelButton />
                                </div>
                            )}
                        </div>
                    </div>
                )}
                <div className="flex w-full justify-between items-start gap-2">
                    {name !== null && (
                        <div className="flex gap-1 [&_svg]:size-6 items-center w-full">
                            <span
                                className={buttonPrimitiveVariants({
                                    size: 'base',
                                    iconOnly: true,
                                    className: 'rounded-sm',
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
                        </div>
                    )}
                    {/* If we're not showing breadcrumbs, we want to show the actions inline with the title */}
                    {!willShowBreadcrumbs && (
                        <div className="shrink-0">
                            {actions && (
                                <div className="flex gap-2 shrink-0 ml-auto">
                                    {actions}
                                    <SceneTitlePanelButton />
                                </div>
                            )}
                        </div>
                    )}
                </div>

                {effectiveDescription !== null && (effectiveDescription || canEdit) && (
                    <div className="flex gap-2 [&_svg]:size-6 items-center w-full group-data-[editable=true]:mt-1">
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
                    </div>
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
        'text-xl font-semibold my-0 pl-[var(--button-padding-x-sm)] min-h-[var(--button-height-base)] group-data-[editable=false]:py-0 leading-[1.4] select-auto'

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
                                className: `${textClasses} field-sizing-content w-full hover:bg-fill-input`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4'
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
                                'flex text-left [&_.LemonIcon]:size-4 h-auto pl-[var(--button-padding-x-sm)]'
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

    const textClasses = 'text-sm my-0 select-auto group-data-[editable=false]:py-0'

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
                                className: `${textClasses} field-sizing-content w-full hover:bg-fill-input`,
                                autoHeight: true,
                            }),
                            '[&_.LemonIcon]:size-4'
                        )}
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
