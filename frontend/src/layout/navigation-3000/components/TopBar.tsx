import './TopBar.scss'

import { IconChevronDown, IconFolderMove, IconFolderOpen, IconShortcut, IconX } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { EditableField } from 'lib/components/EditableField/EditableField'
import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { MetalyticsSummary } from 'lib/components/Metalytics/MetalyticsSummary'
import { TopBarSettingsButton } from 'lib/components/TopBarSettingsButton/TopBarSettingsButton'
import { IconMenu, IconSlash } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import React, { useLayoutEffect, useState } from 'react'

import { ErrorBoundary } from '~/layout/ErrorBoundary'
import { breadcrumbsLogic } from '~/layout/navigation/Breadcrumbs/breadcrumbsLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { Breadcrumb as IBreadcrumb } from '~/types'

/** Sync with --breadcrumbs-height-compact. */
export const BREADCRUMBS_HEIGHT_COMPACT = 44

export function TopBar(): JSX.Element | null {
    const { mobileLayout } = useValues(navigationLogic)
    const { breadcrumbs, renameState } = useValues(breadcrumbsLogic)
    const { setActionsContainer } = useActions(breadcrumbsLogic)
    const { showLayoutNavBar } = useActions(panelLayoutLogic)
    const { isLayoutNavbarVisibleForMobile } = useValues(panelLayoutLogic)
    const { projectTreeRefEntry } = useValues(projectTreeDataLogic)
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { openMoveToModal } = useActions(moveToLogic)
    const [compactionRate, setCompactionRate] = useState(0)
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const { addShortcutItem } = useActions(projectTreeDataLogic)
    // Always show in full on mobile, as there we are very constrained in width, but not so much height
    const effectiveCompactionRate = mobileLayout ? 0 : compactionRate
    const isOnboarding = router.values.location.pathname.includes('/onboarding/')
    const hasRenameState = !!renameState

    useLayoutEffect(() => {
        function handleScroll(): void {
            const mainElement = document.getElementsByTagName('main')[0]
            const mainScrollTop = mainElement.scrollTop
            const compactionDistance = Math.min(
                // This ensures that scrolling to the bottom of the scene will always result in the compact top bar state
                // even if there's just a few pixels of scroll room. Otherwise, the top bar would be halfway-compact then
                mainElement.scrollHeight - mainElement.clientHeight,
                BREADCRUMBS_HEIGHT_COMPACT
            )
            // To avoid flickering effect we need to wait for the element to be visible
            const completionRateTransfer = 0.9
            const newCompactionRate = compactionDistance > 0 ? Math.min(mainScrollTop / compactionDistance, 1) : 0
            setCompactionRate((compactionRate) => {
                if (
                    hasRenameState &&
                    ((newCompactionRate > completionRateTransfer && compactionRate <= completionRateTransfer) ||
                        (newCompactionRate <= completionRateTransfer && compactionRate > completionRateTransfer))
                ) {
                    // Transfer selection from the outgoing input to the incoming one
                    const [source, target] =
                        newCompactionRate > completionRateTransfer ? ['large', 'small'] : ['small', 'large']
                    const sourceEl = document.querySelector<HTMLInputElement>(`input[name="item-name-${source}"]`)
                    const targetEl = document.querySelector<HTMLInputElement>(`input[name="item-name-${target}"]`)
                    if (sourceEl && targetEl) {
                        targetEl.focus()
                        targetEl.setSelectionRange(sourceEl.selectionStart || 0, sourceEl.selectionEnd || 0)
                    }
                }
                return newCompactionRate
            })
        }

        const main = document.getElementsByTagName('main')[0]
        main.addEventListener('scroll', handleScroll)
        return () => main.removeEventListener('scroll', handleScroll)
    }, [hasRenameState])

    return breadcrumbs.length || projectTreeRefEntry ? (
        <div
            className={clsx(
                'TopBar3000',
                effectiveCompactionRate === 0 && 'TopBar3000--full',
                effectiveCompactionRate === 1 && 'TopBar3000--compact'
            )}
            // eslint-disable-next-line react/forbid-dom-props
            style={{ '--breadcrumbs-compaction-rate': effectiveCompactionRate } as React.CSSProperties}
        >
            <div className="TopBar3000__content">
                {mobileLayout && (
                    <LemonButton
                        size="small"
                        onClick={() => showLayoutNavBar(!isLayoutNavbarVisibleForMobile)}
                        icon={isLayoutNavbarVisibleForMobile ? <IconX /> : <IconMenu />}
                        className="TopBar3000__hamburger"
                    />
                )}
                <div className="TopBar3000__breadcrumbs">
                    {breadcrumbs.length > 1 && (
                        <div className="TopBar3000__trail">
                            {breadcrumbs.slice(0, -1).map((breadcrumb) => (
                                <React.Fragment key={joinBreadcrumbKey(breadcrumb.key)}>
                                    <Breadcrumb breadcrumb={breadcrumb} />
                                    <div className="TopBar3000__separator">
                                        <IconSlash fontSize="1rem" />
                                    </div>
                                </React.Fragment>
                            ))}
                            {projectTreeRefEntry && (
                                <>
                                    <LemonButton
                                        size="xsmall"
                                        onClick={() => {
                                            assureVisibility({ type: 'folder', ref: projectTreeRefEntry.path })
                                            showLayoutPanel(true)
                                            setActivePanelIdentifier('Project')
                                        }}
                                        icon={<IconFolderOpen />}
                                        data-attr="top-bar-open-in-project-tree-button"
                                        tooltip="Open in project tree"
                                        disabledReason={renameState ? "Can't view in tree while renaming" : ''}
                                    />
                                    <LemonButton
                                        size="xsmall"
                                        onClick={() => openMoveToModal([projectTreeRefEntry])}
                                        icon={<IconFolderMove />}
                                        data-attr="top-bar-move-button"
                                        tooltip="Move to another folder"
                                        disabledReason={renameState ? "Can't move while renaming" : ''}
                                    />
                                    <LemonButton
                                        size="xsmall"
                                        onClick={() => addShortcutItem(projectTreeRefEntry)}
                                        icon={<IconShortcut />}
                                        data-attr="top-bar-add-to-shortcuts-button"
                                        tooltip="Add to shortcuts panel"
                                        disabledReason={renameState ? "Can't add to shortcuts while renaming" : ''}
                                    />
                                </>
                            )}
                            <Breadcrumb
                                breadcrumb={breadcrumbs[breadcrumbs.length - 1]}
                                here
                                isOnboarding={isOnboarding}
                            />
                        </div>
                    )}
                    <Here breadcrumb={breadcrumbs[breadcrumbs.length - 1]} isOnboarding={isOnboarding} />
                </div>
                <FlaggedFeature flag="metalytics">
                    <div className="shrink-1">
                        <MetalyticsSummary />
                    </div>
                </FlaggedFeature>
                <div className="TopBar3000__actions border-danger" ref={setActionsContainer} />
                <div className="shrink-1">
                    <TopBarSettingsButton />
                </div>
            </div>
        </div>
    ) : null
}

interface BreadcrumbProps {
    breadcrumb: IBreadcrumb
    here?: boolean
    isOnboarding?: boolean
}

function Breadcrumb({ breadcrumb, here, isOnboarding }: BreadcrumbProps): JSX.Element {
    const { renameState } = useValues(breadcrumbsLogic)
    const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)
    const { assureVisibility } = useActions(projectTreeLogic({ key: PROJECT_TREE_KEY }))
    const { showLayoutPanel, setActivePanelIdentifier } = useActions(panelLayoutLogic)
    const [popoverShown, setPopoverShown] = useState(false)

    const joinedKey = joinBreadcrumbKey(breadcrumb.key)

    const breadcrumbName = isOnboarding && here ? 'Onboarding' : (breadcrumb.name as string)

    let nameElement: JSX.Element
    if (breadcrumb.symbol) {
        nameElement = breadcrumb.symbol
    } else if (breadcrumb.name != null && breadcrumb.onRename) {
        nameElement = (
            <EditableField
                name="item-name-small"
                value={renameState && renameState[0] === joinedKey ? renameState[1] : breadcrumbName}
                onChange={(newName) => tentativelyRename(joinedKey, newName)}
                onSave={(newName) => {
                    void breadcrumb.onRename?.(newName)
                }}
                mode={renameState && renameState[0] === joinedKey ? 'edit' : 'view'}
                onModeToggle={(newMode) => {
                    if (newMode === 'edit') {
                        tentativelyRename(joinedKey, breadcrumbName)
                    } else {
                        finishRenaming()
                    }
                    setPopoverShown(false)
                }}
                placeholder="Unnamed"
                compactButtons="xsmall"
                editingIndication="underlined"
            />
        )
    } else {
        nameElement = (
            <span className="flex items-center gap-1.5">
                {breadcrumbName === '' ? <em>Unnamed</em> : breadcrumbName}
                {'tag' in breadcrumb && breadcrumb.tag && <LemonTag size="small">{breadcrumb.tag}</LemonTag>}
            </span>
        )
    }

    const isProjectTreeFolder = Boolean(
        breadcrumb.name && breadcrumb.path && 'type' in breadcrumb && breadcrumb.type === 'folder'
    )

    const Component = !isProjectTreeFolder && breadcrumb.path ? Link : 'div'
    const breadcrumbContent = (
        <Component
            className={clsx(
                'TopBar3000__breadcrumb',
                popoverShown && 'TopBar3000__breadcrumb--open',
                (breadcrumb.path || breadcrumb.popover) && 'TopBar3000__breadcrumb--actionable',
                here && 'TopBar3000__breadcrumb--here'
            )}
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
        >
            {nameElement}
            {breadcrumb.popover && !breadcrumb.symbol && <IconChevronDown />}
        </Component>
    )

    if (breadcrumb.popover) {
        return (
            <Popover
                {...breadcrumb.popover}
                visible={popoverShown}
                onClickOutside={() => {
                    if (popoverShown) {
                        setPopoverShown(false)
                    }
                }}
                onClickInside={() => {
                    if (popoverShown) {
                        setPopoverShown(false)
                    }
                }}
            >
                {breadcrumbContent}
            </Popover>
        )
    }

    return <ErrorBoundary>{breadcrumbContent}</ErrorBoundary>
}

interface HereProps {
    breadcrumb: IBreadcrumb
    isOnboarding?: boolean
}

function Here({ breadcrumb, isOnboarding }: HereProps): JSX.Element {
    const { renameState } = useValues(breadcrumbsLogic)
    const { tentativelyRename, finishRenaming } = useActions(breadcrumbsLogic)

    const joinedKey = joinBreadcrumbKey(breadcrumb.key)
    const hereName = isOnboarding ? 'Onboarding' : (breadcrumb.name as string)

    return (
        <h1 className="TopBar3000__here" data-attr="top-bar-name">
            {breadcrumb.name == null ? (
                <LemonSkeleton className="w-40 h-4" />
            ) : breadcrumb.onRename ? (
                <EditableField
                    name="item-name-large"
                    value={renameState && renameState[0] === joinedKey ? renameState[1] : hereName}
                    onChange={(newName) => {
                        tentativelyRename(joinedKey, newName)
                        if (breadcrumb.forceEditMode) {
                            // In this case there's no "Save" button, we update on input
                            void breadcrumb.onRename?.(newName)
                        }
                    }}
                    onSave={(newName) => {
                        void breadcrumb.onRename?.(newName)
                    }}
                    mode={renameState && renameState[0] === joinedKey ? 'edit' : 'view'}
                    onModeToggle={(newMode) => {
                        if (newMode === 'edit') {
                            tentativelyRename(joinedKey, hereName)
                        } else {
                            finishRenaming()
                        }
                    }}
                    saveOnBlur={breadcrumb.forceEditMode}
                    placeholder="Unnamed"
                    compactButtons="xsmall"
                    editingIndication="underlined"
                    autoFocus
                />
            ) : (
                <span>{hereName}</span>
            )}
        </h1>
    )
}

function joinBreadcrumbKey(key: IBreadcrumb['key']): string {
    return Array.isArray(key) ? key.map(String).join(':') : String(key)
}
