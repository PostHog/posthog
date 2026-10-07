import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { ProductSetupButton } from 'lib/components/ProductSetup'
import { releaseStageProductForScene } from 'lib/components/ReleaseStageTag/releaseStage'
import { ReleaseStageTag } from 'lib/components/ReleaseStageTag/ReleaseStageTag'
import { sceneLogic } from 'scenes/sceneLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'

import { sceneLayoutLogic } from '../sceneLayoutLogic'
import { QuillSceneHeader } from './QuillSceneHeader'
import { QuillSceneName } from './QuillSceneName'
import { SceneBreadcrumbBackButton } from './SceneBreadcrumbs'
import { SceneDescription } from './SceneDescription'
import { sceneResourceIcon } from './sceneResourceIcon'
import { SceneTitlePanelButton } from './SceneTitlePanelButton'
import type { SceneMainTitleProps } from './SceneTitleSection'

export function QuillSceneTitleSection({
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
}: SceneMainTitleProps): JSX.Element {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const { showDescription } = useValues(sceneLayoutLogic)
    const { toggleShowDescription } = useActions(sceneLayoutLogic)
    const { phoneHeaderShown, currentWarehouseItem } = useValues(todayShellLogic)
    // The phone header shows the title, so this row keeps only the actions. A new resource keeps its name field.
    const titleInPhoneHeader = phoneHeaderShown && !forceEdit
    const nestedPage = !!forceBackTo || breadcrumbs.length > 2
    // The warehouse header names each top-level warehouse page. A nested page keeps its title, because the header does not show the resource name.
    const titleInWarehouseHeader = !!currentWarehouseItem && !nestedPage && !forceEdit
    const releaseStageSceneId = sceneId ?? activeSceneId
    const releaseStageProduct = useMemo(
        () => releaseStageProductForScene(releaseStageSceneId, name),
        [releaseStageSceneId, name]
    )
    const hasDescription = description != null && (description || canEdit)
    const descriptionShown =
        hasDescription && (descriptionAlwaysVisible || (showDescription && !titleInPhoneHeader) || forceEdit)
    const sceneActions = (
        <>
            {!hideProductSetupButton && <ProductSetupButton />}
            {actions}
            <SceneTitlePanelButton maxToolProps={maxToolProps} maxButtonLabel={maxButtonLabel} />
        </>
    )

    if (titleInWarehouseHeader) {
        return (
            <div data-quill className={cn('flex flex-wrap items-center justify-end gap-1 empty:hidden', className)}>
                {sceneActions}
            </div>
        )
    }

    return (
        <>
            <QuillSceneHeader
                className={cn(
                    'z-30 bg-[var(--scene-layout-background)] @2xl/main-content:sticky -top-[calc(var(--spacing)*4)]',
                    !noPadding && '-mx-4 -mt-4',
                    titleInPhoneHeader && 'hidden has-[>div>*]:flex',
                    className
                )}
                back={
                    !titleInPhoneHeader && nestedPage ? (
                        <SceneBreadcrumbBackButton forceBackTo={forceBackTo} />
                    ) : undefined
                }
                icon={name !== null && !titleInPhoneHeader ? sceneResourceIcon(resourceType) : undefined}
                title={
                    name !== null &&
                    !titleInPhoneHeader && (
                        <QuillSceneName
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
                                    {hasDescription && !descriptionAlwaysVisible && (
                                        <Button
                                            variant="default"
                                            size="icon-sm"
                                            aria-label={showDescription ? 'Hide description' : 'Show description'}
                                            onClick={toggleShowDescription}
                                            data-attr={
                                                showDescription
                                                    ? 'toggle-description-button-collapse'
                                                    : 'toggle-description-button-expand'
                                            }
                                        >
                                            {showDescription || forceEdit ? <IconCollapse /> : <IconExpand />}
                                        </Button>
                                    )}
                                </>
                            }
                        />
                    )
                }
                actions={sceneActions}
            />
            {descriptionShown && (
                <div className={cn('[&_svg]:size-6', noPadding && cn('pl-4 pr-2', className))}>
                    <SceneDescription
                        description={description}
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
            )}
        </>
    )
}
