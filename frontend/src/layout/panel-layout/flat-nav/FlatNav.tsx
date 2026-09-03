import './FlatNav.scss'

import { cva } from 'cva'
import { useActions, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconChat, IconClock, IconHome, IconNotification, IconPlusSmall } from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { NavSearchBar, NavSearchButton } from 'lib/components/NavSearchButton/NavSearchButton'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { ScrollableShadows } from 'lib/components/ScrollableShadows/ScrollableShadows'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useShortcut } from 'lib/components/Shortcuts/useShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from 'lib/ui/DropdownMenu/DropdownMenu'
import { cn } from 'lib/utils/css-classes'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { urls } from 'scenes/urls'

import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { NavLink } from '~/layout/panel-layout/ai-first/NavLink'
import { PanelLayoutPanels } from '~/layout/panel-layout/ai-first/PanelLayoutPanels'
import { CreateMenu } from '~/layout/panel-layout/menus/CreateMenu'
import { NavBarFooter } from '~/layout/panel-layout/NavBarFooter'
import {
    PANEL_NAVBAR_COLLAPSE_THRESHOLD,
    PANEL_NAVBAR_DEFAULT_WIDTH,
    panelLayoutLogic,
} from '~/layout/panel-layout/panelLayoutLogic'
import { uiCustomizationLogic } from '~/layout/uiCustomizationLogic'
import { ActivityTab } from '~/types'

import { FlatNavPanelButtons } from './FlatNavPanelButtons'
import { FlatNavProducts } from './FlatNavProducts'
import { FlatNavRecents } from './FlatNavRecents'

const flatNavStyles = cva({
    base: 'FlatNav flex flex-col max-h-screen min-h-screen bg-surface-tertiary z-[var(--z-layout-navbar)] relative border-r lg:border-r-transparent',
    variants: {
        isLayoutNavCollapsed: {
            true: 'w-[var(--project-navbar-width-collapsed)]',
            false: 'w-[var(--project-navbar-width)]',
        },
        isMobileLayout: {
            true: 'absolute top-0 bottom-0 left-0',
            false: '',
        },
    },
})

// Keeps newDashboardLogic mounted while the Create button is visible, so the "Start from scratch"
// flow completes (and redirects) even after the menu closes and unmounts its own logic reference.
function CreateMenuLogics(): null {
    useMountedLogic(newDashboardLogic)
    return null
}

export function FlatNav(): JSX.Element {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const { toggleLayoutNavCollapsed, setNavbarWidth } = useActions(panelLayoutLogic)
    const { isLayoutPanelVisible, isLayoutNavCollapsed } = useValues(panelLayoutLogic)
    const { mobileLayout: isMobileLayout } = useValues(navigation3000Logic)
    const { toggleCommand } = useActions(commandLogic)
    const { sidebarDensity, isSidebarSectionShown, isSidebarItemShown, uiCustomizationEnabled } =
        useValues(uiCustomizationLogic)
    const { showConfigureHomeModal } = useActions(navigationLogic)
    const isProductAutonomyEnabled = useFeatureFlag('PRODUCT_AUTONOMY')
    const showCreateButton = useFeatureFlag('CREATE_BUTTON_NAV_EXPERIMENT', 'test')

    const resizerLogicProps: ResizerLogicProps = {
        logicKey: 'panel-layout-navbar',
        placement: 'right',
        containerRef,
        persistent: true,
        closeThreshold: PANEL_NAVBAR_COLLAPSE_THRESHOLD,
        onToggleClosed: (shouldBeClosed) => toggleLayoutNavCollapsed(shouldBeClosed),
        onDoubleClick: () => toggleLayoutNavCollapsed(),
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    // Grow to any width upward; never render narrower than the collapse snap so the live drag
    // stays in sync with where onToggleClosed flips to collapsed mode.
    const openWidth = Math.max(Math.round(desiredSize ?? PANEL_NAVBAR_DEFAULT_WIDTH), PANEL_NAVBAR_COLLAPSE_THRESHOLD)

    useEffect(() => {
        if (!isLayoutNavCollapsed && !isMobileLayout) {
            setNavbarWidth(openWidth)
        }
    }, [openWidth, isLayoutNavCollapsed, isMobileLayout, setNavbarWidth])

    useShortcut({
        name: 'ToggleLeftNav',
        keybind: [keyBinds.toggleLeftNav],
        intent: 'Toggle collapse left navigation',
        interaction: 'function',
        callback: toggleLayoutNavCollapsed,
    })

    return (
        <div className="flex gap-0 relative">
            <nav
                className={cn(flatNavStyles({ isLayoutNavCollapsed, isMobileLayout }))}
                data-nav-density={sidebarDensity}
                ref={containerRef}
            >
                <div
                    className={cn(
                        'flex justify-between items-center',
                        isLayoutNavCollapsed ? 'justify-center' : 'h-[var(--scene-layout-header-height)]'
                    )}
                >
                    <div
                        className={cn('flex gap-1 rounded-md w-full px-2 pt-2 pb-1', {
                            'flex-col items-center pt-2 pb-0': isLayoutNavCollapsed,
                        })}
                    >
                        <NewAccountMenu isLayoutNavCollapsed={isLayoutNavCollapsed} />

                        {/* Collapsed nav has no room for the search bar, so it keeps the icon-only trigger */}
                        {isLayoutNavCollapsed && <NavSearchButton toggleCommand={toggleCommand} />}
                    </div>
                </div>

                {!isLayoutNavCollapsed && (
                    <div className="px-2 py-1">
                        <NavSearchBar toggleCommand={toggleCommand} />
                    </div>
                )}

                {showCreateButton && (
                    <div className={cn('px-2 py-1', isLayoutNavCollapsed && 'flex justify-center px-0')}>
                        <CreateMenuLogics />
                        <DropdownMenu
                            onOpenChange={(open) => {
                                if (open) {
                                    posthog.capture('nav create button clicked')
                                }
                            }}
                        >
                            <DropdownMenuTrigger asChild>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    icon={<IconPlusSmall />}
                                    fullWidth={!isLayoutNavCollapsed}
                                    center={!isLayoutNavCollapsed}
                                    title={isLayoutNavCollapsed ? 'Create' : undefined}
                                    data-attr="nav-create-button"
                                >
                                    {!isLayoutNavCollapsed ? 'Create' : null}
                                </LemonButton>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent side="bottom" align="start" className="min-w-[220px]">
                                <CreateMenu />
                            </DropdownMenuContent>
                        </DropdownMenu>
                    </div>
                )}

                <ScrollableShadows
                    className="flex-1"
                    innerClassName="overflow-y-auto overflow-x-hidden pl-2 pr-0.5 pt-1 focus-visible:outline-accent -outline-offset-2"
                    direction="vertical"
                    styledScrollbars
                >
                    <div className={cn('flex flex-col gap-px', isLayoutNavCollapsed && 'items-center')}>
                        {isSidebarItemShown('home') && (
                            <NavLink
                                to={urls.projectRoot()}
                                label="Home"
                                icon={<IconHome />}
                                isCollapsed={isLayoutNavCollapsed}
                                data-attr="nav-item-home"
                                onClick={() => posthog.capture('nav item clicked', { item: 'home' })}
                                sideAction={{
                                    onClick: () =>
                                        uiCustomizationEnabled
                                            ? router.actions.push(urls.settings('user-navigation', 'homepage'))
                                            : showConfigureHomeModal(),
                                    tooltip: 'Configure home',
                                    'data-attr': 'nav-configure-home',
                                }}
                            />
                        )}

                        <NavLink
                            to={urls.ai()}
                            label="Chat"
                            icon={<IconChat className="text-ai" />}
                            isCollapsed={isLayoutNavCollapsed}
                            data-attr="flat-nav-item-chat"
                            onClick={() => posthog.capture('nav item clicked', { item: 'chat' })}
                        />

                        {isProductAutonomyEnabled && isSidebarItemShown('inbox') && (
                            <NavLink
                                to={urls.inbox()}
                                label="Self-driving"
                                icon={<IconNotification />}
                                isCollapsed={isLayoutNavCollapsed}
                                data-attr="nav-item-inbox"
                                tag="beta"
                                onClick={() => posthog.capture('nav item clicked', { item: 'inbox' })}
                            />
                        )}

                        <NavLink
                            to={urls.activity(ActivityTab.ExploreEvents)}
                            label="Activity"
                            icon={<IconClock />}
                            isCollapsed={isLayoutNavCollapsed}
                            data-attr="nav-item-activity"
                            onClick={() => posthog.capture('nav item clicked', { item: 'activity' })}
                        />

                        <FlatNavPanelButtons />
                    </div>

                    {!isLayoutNavCollapsed && isSidebarSectionShown('recents') && <FlatNavRecents />}
                    {!isLayoutNavCollapsed && isSidebarSectionShown('my_tools') && <FlatNavProducts />}
                </ScrollableShadows>

                <div className="px-2">
                    <div className="h-px bg-border-primary" />
                </div>

                <div className="p-1">
                    <NavBarFooter isLayoutNavCollapsed={isLayoutNavCollapsed} />
                </div>

                {!isMobileLayout && (
                    <Resizer
                        {...resizerLogicProps}
                        data-attr="tree-navbar-resizer"
                        className={cn('top-3 -right-px bottom-4 z-2', {
                            'top-0': isLayoutPanelVisible,
                        })}
                        offset={0}
                    />
                )}
            </nav>

            {/* Desktop renders panel content inline next to the nav (PanelLayoutPanel's
                ResizableElement positions it via left:100% of this flex parent). On mobile the
                panel is lifted out to PanelLayout.tsx for its own stacking context. */}
            {!isMobileLayout && <PanelLayoutPanels />}
        </div>
    )
}
