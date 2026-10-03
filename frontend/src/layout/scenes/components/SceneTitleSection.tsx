import '../../panel-layout/ProjectTree/defaultTree'

import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef, useState } from 'react'

import { IconCollapse, IconExpand, IconPencil } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { ProductSetupButton } from 'lib/components/ProductSetup'
import { releaseStageProductForScene } from 'lib/components/ReleaseStageTag/releaseStage'
import { ReleaseStageTag } from 'lib/components/ReleaseStageTag/ReleaseStageTag'
import { ButtonPrimitive, buttonPrimitiveVariants } from 'lib/ui/Button/ButtonPrimitives'
import { TextareaPrimitive } from 'lib/ui/TextareaPrimitive/TextareaPrimitive'
import { WrappingLoadingSkeleton } from 'lib/ui/WrappingLoadingSkeleton/WrappingLoadingSkeleton'
import { cn } from 'lib/utils/css-classes'
import { AnimatedSparkles } from 'scenes/max/components/AnimatedSparkles'
import { UseMaxToolOptions } from 'scenes/max/useMaxTool'
import { sceneLogic } from 'scenes/sceneLogic'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { Breadcrumb, FileSystemIconColor } from '~/types'

import { sceneLayoutLogic } from '../sceneLayoutLogic'
import { QuillSceneTitleSection } from './QuillSceneTitleSection'
import { SceneBreadcrumbBackButton } from './SceneBreadcrumbs'
import { SceneDescription } from './SceneDescription'
import { sceneResourceIcon } from './sceneResourceIcon'
import { SceneTitlePanelButton } from './SceneTitlePanelButton'
import { useSceneNameEditing } from './useSceneNameEditing'

export type ResourceType = {
    to?: string
    /** pass in a value from the FileSystemIconType enum, or a string if not available */
    type: FileSystemIconType | string
    /** If your resource type matches a product in fileSystemTypes, you can use this to override the icon */
    forceIcon?: JSX.Element
    /** If your resource type matches a product in fileSystemTypes and has a color defined, you can use this to override the product's icon color */
    forceIconColorOverride?: FileSystemIconColor
}

export type SceneMainTitleProps = {
    /**
     * null to hide the name,
     * undefined to show the default name
     */
    name?: string | null
    /**
     * Optional node rendered inline immediately after the name (e.g. a status tag)
     */
    nameSuffix?: React.ReactNode
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
     * If true, the description is always rendered and the show/hide toggle is omitted
     */
    descriptionAlwaysVisible?: boolean
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
     * If true, removes the vertical padding from the title section
     * */
    noPadding?: boolean
    /**
     * If true, the actions from PageHeader will be shown
     * @default false
     */
    actions?: JSX.Element
    hideProductSetupButton?: boolean
    /**
     * If provided, the back button will be forced to this breadcrumb
     * @default undefined
     */
    forceBackTo?: Breadcrumb

    /**
     * Additional class name for the title section
     */
    className?: string

    /** Optional callback to generate metadata (name + description) using AI — only shown on the title field. */
    onGenerateMetadata?: () => void
    /**
     * Whether metadata generation is currently in progress
     */
    isGeneratingMetadata?: boolean
    /**
     * Props for MaxTool registration - when provided,
     * the AI button in the title section registers the tool with Max
     */
    maxToolProps?: Omit<UseMaxToolOptions, 'active'>
    /** Optional label for the PostHog AI button. */
    maxButtonLabel?: string
    /** Max character length for the description field */
    descriptionMaxLength?: number
    /** The scene whose release stage the title shows, when the title is for a scene other than the active one */
    sceneId?: string | null
}

export function SceneTitleSection(props: SceneMainTitleProps): JSX.Element | null {
    const { zenMode } = useValues(navigation3000Logic)
    const { todayRailEnabled } = useValues(todayShellLogic)
    if (zenMode) {
        return null
    }
    return todayRailEnabled ? <QuillSceneTitleSection {...props} /> : <LemonSceneTitleSection {...props} />
}

function LemonSceneTitleSection({
    name,
    nameSuffix,
    description,
    resourceType,
    markdown = false,
    isLoading = false,
    onNameChange,
    onDescriptionChange,
    canEdit = false,
    forceEdit = false,
    descriptionAlwaysVisible = false,
    renameDebounceMs,
    saveOnBlur = false,
    noBorder = false,
    noPadding = false,
    actions,
    hideProductSetupButton = false,
    forceBackTo,
    className,
    onGenerateMetadata,
    isGeneratingMetadata,
    maxToolProps,
    maxButtonLabel,
    descriptionMaxLength,
    sceneId,
}: SceneMainTitleProps): JSX.Element | null {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const releaseStageSceneId = sceneId ?? activeSceneId
    const releaseStageProduct = useMemo(
        () => releaseStageProductForScene(releaseStageSceneId, name),
        [releaseStageSceneId, name]
    )
    const { showDescription } = useValues(sceneLayoutLogic)
    const { toggleShowDescription } = useActions(sceneLayoutLogic)
    const willShowBreadcrumbs = forceBackTo || breadcrumbs.length > 2
    const [isScrolled, setIsScrolled] = useState(false)
    const sentinelRef = useRef<HTMLDivElement>(null)
    const effectiveDescription = description
    const hasDescription = effectiveDescription != null && (effectiveDescription || canEdit)
    // Always include ProductSetupButton alongside other actions
    // Product auto-selection is handled by SceneContent via globalSetupLogic
    const effectiveActions = (
        <>
            {!hideProductSetupButton && <ProductSetupButton />}
            {actions}
        </>
    )

    useEffect(() => {
        const stickyElement = sentinelRef.current
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
    }, [noBorder])

    const icon = sceneResourceIcon(resourceType)

    const descriptionBlock = hasDescription && (descriptionAlwaysVisible || showDescription || forceEdit) && (
        <div className={cn('[&_svg]:size-6', noPadding ? cn('pl-4 pr-2', className) : '-mt-4')}>
            <SceneDescription
                description={effectiveDescription}
                markdown={markdown}
                isLoading={isLoading}
                onChange={onDescriptionChange}
                canEdit={canEdit}
                forceEdit={forceEdit}
                renameDebounceMs={renameDebounceMs}
                saveOnBlur={saveOnBlur}
                maxLength={descriptionMaxLength}
                isGeneratingMetadata={isGeneratingMetadata}
            />
        </div>
    )

    return (
        <>
            {!noBorder && (
                // When this element scrolls out of view, the IntersectionObserver sets isScrolled=true to show the border
                <div
                    ref={sentinelRef}
                    data-sticky-sentinel
                    className="h-px w-px pointer-events-none absolute -top-4"
                    aria-hidden
                />
            )}

            <div
                className={cn(
                    'group/scene-title-section bg-primary @2xl/main-content:sticky -top-[calc(var(--spacing)*4)] z-30 duration-300',
                    noPadding ? '' : '-mx-4 px-4 -mt-4',
                    noBorder ? '' : 'border-b border-transparent transition-border',
                    isScrolled && '@2xl/main-content:border-primary [body.storybook-test-runner_&]:border-transparent',
                    'pl-4 pr-2',
                    className
                )}
            >
                <div
                    className={cn(
                        'scene-title-section flex-1 flex flex-col @2xl/main-content:flex-row gap-1 lg:gap-3 group/colorful-product-icons colorful-product-icons-true lg:items-start group',
                        noPadding ? 'py-0.5' : 'py-2'
                    )}
                    data-editable={canEdit}
                >
                    <div
                        className={cn('flex items-center gap-1 flex-1 min-w-0', {
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
                                    onGenerateMetadata={onGenerateMetadata}
                                    isGeneratingMetadata={isGeneratingMetadata}
                                    suffix={
                                        <>
                                            {releaseStageProduct && <ReleaseStageTag product={releaseStageProduct} />}
                                            {nameSuffix}
                                            {hasDescription && !descriptionAlwaysVisible ? (
                                                <ButtonPrimitive
                                                    className={cn(
                                                        'size-[var(--button-height-sm)] shrink-0',
                                                        isScrolled
                                                            ? 'animate-fade-out-subtle pointer-events-none'
                                                            : 'animate-fade-in-subtle group-hover/scene-title-section:opacity-100 opacity-30 transition-opacity duration-200 motion-reduce:transition-none'
                                                    )}
                                                    onClick={toggleShowDescription}
                                                    tooltip={showDescription ? 'Hide description' : 'Show description'}
                                                    tooltipPlacement="bottom"
                                                    iconOnly
                                                    data-attr={
                                                        showDescription
                                                            ? 'toggle-description-button-collapse'
                                                            : 'toggle-description-button-expand'
                                                    }
                                                >
                                                    {showDescription || forceEdit ? <IconCollapse /> : <IconExpand />}
                                                </ButtonPrimitive>
                                            ) : undefined}
                                        </>
                                    }
                                />
                                {forceEdit && nameSuffix}
                            </>
                        )}
                    </div>
                    {effectiveActions && (
                        <div
                            className={cn(
                                // relative z-30 keeps the corner actions above the focus-elevated name/description
                                // editors (z-20) so focusing an edit field can never overlap and swallow their clicks,
                                // notably on mobile where this container reflows into the corner via order-first.
                                'relative z-30 flex gap-1.5 justify-end items-end @2xl/main-content:items-start ml-4 @max-2xl:order-first',
                                'gap-1 self-start @max-2xl:self-end flex-wrap'
                            )}
                        >
                            {effectiveActions}
                            <SceneTitlePanelButton maxToolProps={maxToolProps} maxButtonLabel={maxButtonLabel} />
                        </div>
                    )}
                </div>
                {/* Border is handled by the outer container's border-b */}
            </div>
            {descriptionBlock}
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
    onGenerateMetadata?: () => void
    isGeneratingMetadata?: boolean
    suffix?: React.ReactNode
}

export function SceneName({
    name: initialName,
    isLoading = false,
    onChange,
    canEdit = false,
    forceEdit = false,
    renameDebounceMs = 100,
    saveOnBlur = false,
    onGenerateMetadata,
    isGeneratingMetadata = false,
    suffix,
}: SceneNameProps): JSX.Element {
    const { name, isEditing, containerRef, startEditing, change, blur, saveFromEnter } = useSceneNameEditing({
        name: initialName,
        isLoading,
        onChange,
        forceEdit,
        renameDebounceMs,
        saveOnBlur,
        isGeneratingMetadata,
    })

    const textClasses =
        'text-lg font-semibold my-0 pl-[var(--button-padding-x-sm)] min-h-[var(--button-height-sm)] leading-[1.4] select-auto'

    // If onBlur is provided, we want to show a button that allows the user to edit the name
    // Otherwise, we want to show the name as a text
    const Element =
        onChange && canEdit ? (
            <>
                {isEditing ? (
                    <div ref={containerRef} className="flex items-center gap-1 w-full" data-attr="scene-name-edit-row">
                        <TextareaPrimitive
                            variant="default"
                            name="name"
                            value={name || ''}
                            readOnly={isGeneratingMetadata}
                            onChange={(e) => change(e.target.value)}
                            data-attr="scene-title-textarea"
                            className={cn(
                                buttonPrimitiveVariants({
                                    inert: true,
                                    className: `${textClasses} w-full hover:bg-fill-input py-0`,
                                    autoHeight: true,
                                }),
                                '[&_.LemonIcon]:size-4 input-like',
                                isGeneratingMetadata && 'cursor-not-allowed opacity-80'
                            )}
                            wrapperClassName="flex-1 min-w-0"
                            placeholder="Enter name"
                            onBlur={blur}
                            autoFocus={!forceEdit}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                    e.preventDefault()
                                    saveFromEnter(e.currentTarget.value)
                                }
                            }}
                        />
                        {onGenerateMetadata && (
                            <Tooltip title={isGeneratingMetadata ? 'Thinking...' : 'Generate name and description'}>
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (!isGeneratingMetadata) {
                                            onGenerateMetadata()
                                        }
                                    }}
                                    disabled={isGeneratingMetadata}
                                    className="shrink-0 transition duration-50 cursor-pointer hover:scale-110 rounded-md border border-dashed border-accent size-7 backdrop-blur-[2px] bg-[rgba(255,255,255,0.5)] dark:bg-[rgba(0,0,0,0.5)] disabled:opacity-50 disabled:cursor-not-allowed"
                                >
                                    <AnimatedSparkles
                                        triggerAnimation={isGeneratingMetadata}
                                        className="relative size-full pl-0.5 pb-0.5"
                                    />
                                </button>
                            </Tooltip>
                        )}
                    </div>
                ) : (
                    <Tooltip
                        title={
                            isGeneratingMetadata
                                ? 'Finish generating before editing'
                                : canEdit && !forceEdit
                                  ? 'Edit name'
                                  : undefined
                        }
                        placement="top-start"
                        arrowOffset={10}
                    >
                        <ButtonPrimitive
                            className={cn(
                                buttonPrimitiveVariants({ size: 'fit', className: textClasses }),
                                'flex text-left [&_.LemonIcon]:size-4 focus-visible:z-20'
                            )}
                            onClick={startEditing}
                            disabled={isGeneratingMetadata}
                            truncate
                        >
                            <span className="truncate">{name || <span className="text-tertiary">Unnamed</span>}</span>
                            {canEdit && !forceEdit && <IconPencil />}
                        </ButtonPrimitive>
                    </Tooltip>
                )}
            </>
        ) : (
            <h1
                className={cn(
                    buttonPrimitiveVariants({ size: 'base', inert: true, className: `${textClasses} min-w-0 truncate` })
                )}
            >
                <span className="truncate min-w-0">{name || <span className="text-tertiary">Unnamed</span>}</span>
            </h1>
        )

    if (isLoading) {
        return (
            <div className="w-full flex-1 focus-within:z-20">
                <WrappingLoadingSkeleton fullWidth>{Element}</WrappingLoadingSkeleton>
            </div>
        )
    }

    return (
        <div
            data-attr="scene-name"
            className={cn(
                'scene-name flex items-center flex-1 min-w-0 max-w-full',
                !isEditing && onChange && canEdit && 'truncate'
            )}
        >
            {Element}
            {!isEditing && suffix}
        </div>
    )
}
