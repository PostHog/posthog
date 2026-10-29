import { useActions, useValues } from 'kea'
import { useMemo, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

import { releaseStageProductForScene } from 'lib/components/ReleaseStageTag/releaseStage'
import { ReleaseStageTag } from 'lib/components/ReleaseStageTag/ReleaseStageTag'
import { sceneLogic } from 'scenes/sceneLogic'

import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { todayShellLogic } from '~/layout/today/todayShellLogic'
import { TodaySidebarBreadcrumb } from '~/layout/today/TodaySidebarBreadcrumb'

import { sceneLayoutLogic } from '../sceneLayoutLogic'
import { QuillSceneHeader } from './QuillSceneHeader'
import { QuillSceneName } from './QuillSceneName'
import { QuillSceneTrail } from './QuillSceneTrail'
import { SceneDescription } from './SceneDescription'
import { useRegisterSceneMenuBarSlot, useSceneMenuBarSlotFilled } from './SceneMenuBarSlotProvider'
import { sceneResourceIcon } from './sceneResourceIcon'
import type { SceneMainTitleProps } from './SceneTitleSection'
import { SceneTitleSettingsButton } from './SceneTitleSettingsButton'

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
    forceBackTo,
    scope,
    className,
    onGenerateMetadata,
    isGeneratingMetadata,
    descriptionMaxLength,
    sceneId,
}: SceneMainTitleProps): JSX.Element {
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const { activeSceneId } = useValues(sceneLogic)
    const { showDescription } = useValues(sceneLayoutLogic)
    const { toggleShowDescription } = useActions(sceneLayoutLogic)
    const { phoneHeaderShown, sidebarBreadcrumbShown } = useValues(todayShellLogic)
    // The phone header shows the title, so this row keeps only the actions. A new resource keeps its name field.
    const titleInPhoneHeader = phoneHeaderShown && !forceEdit
    const releaseStageSceneId = sceneId ?? activeSceneId
    const releaseStageProduct = useMemo(
        () => releaseStageProductForScene(releaseStageSceneId, name),
        [releaseStageSceneId, name]
    )
    const staticName = name !== null && !titleInPhoneHeader && !(onNameChange && canEdit) && !forceEdit && !isLoading
    const hasDescription = description != null && (description || canEdit)
    const descriptionShown =
        hasDescription &&
        (descriptionAlwaysVisible || (showDescription && !titleInPhoneHeader && !staticName) || forceEdit)
    const backTo = forceBackTo || (breadcrumbs.length > 2 ? breadcrumbs[breadcrumbs.length - 2] : undefined)
    const backPath = !titleInPhoneHeader && backTo && 'path' in backTo ? backTo.path : undefined
    const resourceIcon = name !== null && !titleInPhoneHeader ? sceneResourceIcon(resourceType) : undefined
    const nameSuffixes = (
        // Lemon tags read --success and --warning, which quill redefines as pale fills
        <span data-not-quill className="contents">
            {releaseStageProduct && <ReleaseStageTag product={releaseStageProduct} />}
            {nameSuffix}
        </span>
    )
    const [menuBarSlot, setMenuBarSlot] = useState<HTMLDivElement | null>(null)
    useRegisterSceneMenuBarSlot(menuBarSlot)
    // The menu bar's Help menu carries the settings link, so the title shows its own only without a bar.
    const menuBarShown = useSceneMenuBarSlotFilled()

    return (
        <>
            <QuillSceneHeader
                className={cn(
                    'z-30 bg-[var(--scene-layout-background)] @2xl/main-content:sticky -top-[calc(var(--spacing)*4)]',
                    !noPadding && '-mx-4',
                    titleInPhoneHeader && 'hidden has-[>div>*]:flex',
                    className,
                    // Last, so a caller's spacing cannot move the row. The sidebar toggle must sit on the same spot in
                    // every scene. The menu bar portals into the row, so callers that make room for it above need not.
                    'px-4',
                    !noPadding && '-mt-4'
                )}
                back={
                    <QuillSceneTrail
                        lead={sidebarBreadcrumbShown && <TodaySidebarBreadcrumb />}
                        parent={
                            backTo && backPath
                                ? { name: backTo.name, path: backPath }
                                : scope && !titleInPhoneHeader
                                  ? { name: scope }
                                  : undefined
                        }
                        icon={resourceIcon}
                        iconLeadsName={resourceType.iconLeadsName}
                        current={staticName ? { name, description: description || undefined } : undefined}
                    />
                }
                title={
                    <>
                        {staticName && nameSuffixes}
                        {name !== null && !titleInPhoneHeader && !staticName && (
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
                                        {nameSuffixes}
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
                        )}
                        {/* The scene menu bar portals in here, so its menus follow the name after a short divider. A narrow scene wraps
                            the menus onto their own line, where the divider would lead the line, so it hides there. */}
                        <div
                            ref={setMenuBarSlot}
                            className="flex shrink-0 items-center empty:hidden before:mx-1 before:h-4 before:w-px before:shrink-0 before:bg-[var(--border)] before:content-[''] @max-xl/main-content:before:hidden"
                        />
                    </>
                }
                actions={
                    <>
                        {actions}
                        {!menuBarShown && <SceneTitleSettingsButton />}
                    </>
                }
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
