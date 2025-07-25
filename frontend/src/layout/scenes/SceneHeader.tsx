import { IconChevronDown, IconGear, IconInfo, IconPencil, IconX } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconMenu, IconSlash } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { cn } from 'lib/utils/css-classes'
import React, { useState } from 'react'

import { EditableField } from 'lib/components/EditableField/EditableField'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { TopBarSettingsButton } from 'lib/components/TopBarSettingsButton/TopBarSettingsButton'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { Breadcrumb as IBreadcrumb } from '~/types'
import { ProjectDropdownMenu } from '../panel-layout/ProjectDropdownMenu'
import { sceneLayoutLogic } from './sceneLayoutLogic'

export function SceneHeader({ className }: { className?: string }): JSX.Element | null {
    const { mobileLayout } = useValues(navigationLogic)
    const { breadcrumbs } = useValues(breadcrumbsLogic)
    const { setActionsContainer } = useActions(breadcrumbsLogic)
    const { showLayoutNavBar } = useActions(panelLayoutLogic)
    const { isLayoutNavbarVisibleForMobile } = useValues(panelLayoutLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { scenePanelOpen, scenePanelIsPresent, scenePanelIsOverlay } = useValues(sceneLayoutLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)

    return breadcrumbs.length || projectTreeRefEntry ? (
        <>
            <div
                className={cn(
                    'flex items-center gap-1 w-full py-1 px-4 sticky top-0 bg-surface-secondary z-[var(--z-top-navigation)] border-b border-primary h-[var(--scene-layout-header-height)]',
                    className
                )}
            >
                {mobileLayout && (
                    <LemonButton
                        size="small"
                        onClick={() => showLayoutNavBar(!isLayoutNavbarVisibleForMobile)}
                        icon={isLayoutNavbarVisibleForMobile ? <IconX /> : <IconMenu />}
                        className="-ml-2"
                    />
                )}
                <div className="flex gap-1 justify-between w-full items-center overflow-x-hidden py-1">
                    {breadcrumbs.length > 0 && (
                        <ScrollableShadows
                            direction="horizontal"
                            styledScrollbars
                            className="h-[var(--scene-layout-header-height)] pr-2 flex-1"
                            innerClassName="flex gap-0 flex-1 items-center overflow-x-auto show-scrollbar-on-hover h-full"
                        >
                            {breadcrumbs.map((breadcrumb, index) => (
                                <React.Fragment key={joinBreadcrumbKey(breadcrumb.key)}>
                                    <Breadcrumb breadcrumb={breadcrumb} here={index === breadcrumbs.length - 1} />
                                    {index < breadcrumbs.length - 1 && (
                                        <span className="flex items-center shrink-0 opacity-50">
                                            <IconSlash fontSize="1rem" />
                                        </span>
                                    )}
                                </React.Fragment>
                            ))}
                        </ScrollableShadows>
                    )}

                    <div
                        className={cn('flex gap-1 items-center shrink-0', {
                            'pr-px': !scenePanelIsOverlay,
                        })}
                    >
                        <div className="contents" ref={setActionsContainer} />

                        {scenePanelIsPresent && scenePanelIsOverlay && (
                            <LemonButton
                                onClick={() => setScenePanelOpen(!scenePanelOpen)}
                                icon={<IconInfo className="text-primary" />}
                                tooltip={scenePanelOpen ? 'Close info panel' : 'Open info panel'}
                                active={scenePanelOpen}
                                size="small"
                            />
                        )}

                        <TopBarSettingsButton buttonProps={{ size: 'small', icon: <IconGear /> }} />
                    </div>
                </div>
            </div>
        </>
    ) : null
}

interface BreadcrumbProps {
    breadcrumb: IBreadcrumb
    here?: boolean
    isOnboarding?: boolean
}

function Breadcrumb({ breadcrumb, here, isOnboarding }: BreadcrumbProps): JSX.Element {
    const [popoverShown, setPopoverShown] = useState(false)
    const [isEditing, setIsEditing] = useState(false)

    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { scenePanelOpen, scenePanelIsPresent } = useValues(sceneLayoutLogic)
    const { setScenePanelOpen } = useActions(sceneLayoutLogic)
    const { renameState } = useValues(breadcrumbsLogic)
    const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)

    const joinedKey = joinBreadcrumbKey(breadcrumb.key)

    const breadcrumbName = isOnboarding && here ? 'Onboarding' : (breadcrumb.name as string)

    let nameElement: JSX.Element
    if (breadcrumb.symbol) {
        nameElement = breadcrumb.symbol
    } else {
        nameElement = (
            <span className={cn('items-center gap-1.5 inline-block whitespace-nowrap')}>
                {breadcrumbName === '' ? <em>Unnamed</em> : breadcrumbName}
                {'tag' in breadcrumb && breadcrumb.tag && <LemonTag size="small">{breadcrumb.tag}</LemonTag>}
            </span>
        )
    }

    const isProjectTreeFolder = Boolean(
        breadcrumb.name && breadcrumb.path && 'type' in breadcrumb && breadcrumb.type === 'folder'
    )

    const Component = !isProjectTreeFolder && breadcrumb.path ? Link : 'span'
    const breadcrumbContent = (
        <Component
            onClick={() => {
                breadcrumb.popover && setPopoverShown(!popoverShown)
                if (isProjectTreeFolder && breadcrumb.path) {
                    assureVisibility({ type: 'folder', ref: breadcrumb.path })
                    showLayoutPanel(true)
                    setActivePanelIdentifier('Project')
                }
            }}
            data-attr={`breadcrumb-${joinedKey}`}
            to={breadcrumb.path}
            className={cn('text-primary text-sm inline-grid', {
                'font-bold': here,
            })}
        >
            {nameElement}
            {breadcrumb.popover && !breadcrumb.symbol && <IconChevronDown />}
        </Component>
    )

    if (breadcrumb.isPopoverProject) {
        return (
            <ProjectDropdownMenu
                buttonProps={{
                    size: 'xxs',
                    className: 'text-primary font-normal p-0 hover:text-primary gap-1',
                }}
            />
        )
    }

    return (
        <ErrorBoundary>
            {/* if renaming exists, show a button to rename */}
            {/* if renaming exists, show a button to rename */}
            {'onRename' in breadcrumb && breadcrumb.onRename ? (
                <>
                    {isEditing ? (
                        <EditableField
                            name="item-name-small"
                            value={renameState && renameState[0] === joinedKey ? renameState[1] : breadcrumbName}
                            onChange={(newName) => tentativelyRename(joinedKey, newName)}
                            onSave={(newName) => {
                                void breadcrumb.onRename?.(newName)
                            }}
                            mode="edit"
                            onModeToggle={(newMode) => {
                                if (newMode === 'edit') {
                                    tentativelyRename(joinedKey, breadcrumbName)
                                } else {
                                    finishRenaming()
                                }
                                setPopoverShown(false)
                                setIsEditing(false)
                            }}
                            autoFocus
                            placeholder="Unnamed"
                            compactButtons="xsmall"
                            editingIndication="underlined"
                        />
                    ) : (
                        <>
                            {breadcrumbContent}
                            <ButtonPrimitive
                                iconOnly
                                onClick={() => {
                                    if (scenePanelIsPresent) {
                                        setScenePanelOpen(!scenePanelOpen)
                                    } else {
                                        setIsEditing(!isEditing)
                                    }
                                }}
                                className="ml-1"
                                tooltip={scenePanelIsPresent ? 'Editing has moved to the info panel' : 'Rename'}
                            >
                                <IconPencil className="text-primary" />
                            </ButtonPrimitive>
                        </>
                    )}
                </>
            ) : (
                breadcrumbContent
            )}
        </ErrorBoundary>
    )
}

function joinBreadcrumbKey(key: IBreadcrumb['key']): string {
    return Array.isArray(key) ? key.map(String).join(':') : String(key)
}
