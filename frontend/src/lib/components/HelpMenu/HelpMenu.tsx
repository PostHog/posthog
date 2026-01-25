import { useActions, useValues } from 'kea'

import {
    IconBook,
    IconConfetti,
    IconDatabase,
    IconEllipsis,
    IconExpand45,
    IconFeatures,
    IconGear,
    IconLive,
    IconOpenSidebar,
    IconQuestion,
    IconServer,
    IconShieldLock,
    IconSupport,
} from '@posthog/icons'

import { Logomark } from 'lib/brand/Logomark'
import { Link } from 'lib/lemon-ui/Link/Link'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { SidePanelStatusIcon } from '~/layout/navigation-3000/sidepanel/panels/SidePanelStatus'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { appShortcutLogic } from '../AppShortcuts/appShortcutLogic'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { openCHQueriesDebugModal } from '../AppShortcuts/utils/DebugCHQueries'
import { ThemeMenu } from '../Menus/ThemeMenu'
import { helpMenuLogic } from './helpMenuLogic'

export function HelpMenu(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { isHelpMenuOpen } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { user } = useValues(userLogic)
    const { isCloud, preflight } = useValues(preflightLogic)

    return (
        <DropdownMenu open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen}>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    tooltip={
                        <>
                            Help menu
                            <RenderKeybind keybind={[keyBinds.helpMenu]} className="ml-1" />
                        </>
                    }
                    iconOnly
                    className="group"
                >
                    <span className="flex text-secondary group-hover:text-primary">
                        <IconQuestion className="size-5" />
                    </span>
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                side="top"
                align="start"
                sideOffset={8}
                className="min-w-[250px] flex flex-col gap-1"
                collisionPadding={{ left: 0 }}
                loop
            >
                <DropdownMenuGroup className="pt-2 px-2">
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.ai()}
                            buttonProps={{
                                menuItem: true,
                                size: 'fit',
                                className:
                                    'flex flex-col gap-1 p-2 border border-primary rounded h-32 items-center justify-center',
                            }}
                        >
                            <span className="size-3 [&>svg]:size-4">
                                <Logomark />
                            </span>
                            <span className="text-sm font-medium">Ask PostHog AI</span>
                            <span className="text-xs text-tertiary text-center text-pretty">
                                PostHog AI answers 80%+ of support questions we receive!
                            </span>
                        </Link>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuGroup className="flex flex-col gap-px pt-0">
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => openSidePanel(SidePanelTab.Support)}>
                            <IconSupport />
                            Support
                            <IconOpenSidebar className="size-3" />
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
                            to="https://posthog.com/docs"
                            buttonProps={{ menuItem: true }}
                            target="_blank"
                            targetBlankIcon
                            disableDocsPanel
                            tooltip="Open docs in new tab"
                            tooltipPlacement="right"
                        >
                            <IconBook />
                            Docs
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link to={urls.settings()} buttonProps={{ menuItem: true }}>
                            <IconGear />
                            Settings
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
                            targetBlankIcon
                            target="_blank"
                            buttonProps={{ menuItem: true }}
                            to="https://status.posthog.com"
                        >
                            <SidePanelStatusIcon className="flex" size="xsmall" />
                            PostHog status
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
                            tooltip="View our changelog"
                            tooltipPlacement="right"
                            targetBlankIcon
                            target="_blank"
                            buttonProps={{ menuItem: true }}
                            to="https://posthog.com/changelog"
                        >
                            <IconLive />
                            Changelog
                        </Link>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
                            to={urls.settings('user-feature-previews')}
                            buttonProps={{
                                menuItem: true,
                            }}
                            data-attr="top-menu-feature-previews"
                            tooltip="View and access upcoming features"
                            tooltipPlacement="right"
                        >
                            <IconFeatures />
                            Feature previews
                        </Link>
                    </DropdownMenuItem>
                    {user?.is_staff && <></>}
                    {!isCloud && (
                        <DropdownMenuItem asChild>
                            <Link
                                to={urls.moveToPostHogCloud()}
                                buttonProps={{
                                    menuItem: true,
                                }}
                                data-attr="top-menu-item-upgrade-to-cloud"
                            >
                                <IconConfetti />
                                Try PostHog Cloud
                            </Link>
                        </DropdownMenuItem>
                    )}

                    {user?.is_staff && (
                        <DropdownMenuSub>
                            <DropdownMenuSubTrigger asChild>
                                <ButtonPrimitive menuItem>
                                    <IconBlank />
                                    Admin (lucky you!)
                                    <MenuOpenIndicator intent="sub" />
                                </ButtonPrimitive>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent className="min-w-[250px]">
                                <DropdownMenuGroup>
                                    <DropdownMenuItem asChild>
                                        <Link
                                            to="/admin/"
                                            buttonProps={{
                                                menuItem: true,
                                            }}
                                            data-attr="top-menu-django-admin"
                                            disableClientSideRouting
                                        >
                                            <IconShieldLock />
                                            Django admin
                                        </Link>
                                    </DropdownMenuItem>
                                    <DropdownMenuItem asChild>
                                        <Link
                                            to={urls.instanceStatus()}
                                            buttonProps={{
                                                menuItem: true,
                                            }}
                                            tooltip="Async migrations"
                                            tooltipPlacement="right"
                                            data-attr="top-menu-instance-panel"
                                        >
                                            <IconServer />
                                            Instance panel
                                        </Link>
                                    </DropdownMenuItem>

                                    {user?.is_impersonated ||
                                    preflight?.is_debug ||
                                    preflight?.instance_preferences?.debug_queries ? (
                                        <DropdownMenuItem asChild>
                                            <ButtonPrimitive
                                                menuItem
                                                onClick={() => {
                                                    openCHQueriesDebugModal()
                                                }}
                                                data-attr="menu-item-debug-ch-queries"
                                            >
                                                <IconDatabase />
                                                Debug CH queries
                                                <KeyboardShortcut command option tab className="ml-auto" />
                                            </ButtonPrimitive>
                                        </DropdownMenuItem>
                                    ) : null}
                                </DropdownMenuGroup>
                            </DropdownMenuSubContent>
                        </DropdownMenuSub>
                    )}
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger asChild>
                            <ButtonPrimitive menuItem>
                                <IconEllipsis />
                                More
                                <MenuOpenIndicator intent="sub" />
                            </ButtonPrimitive>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="min-w-[250px]">
                            <DropdownMenuGroup>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive
                                        tooltip="Open shortcut menu"
                                        tooltipPlacement="right"
                                        onClick={() => setAppShortcutMenuOpen(true)}
                                        menuItem
                                    >
                                        <span className="size-4 flex items-center justify-center">⌘</span>
                                        Shortcuts
                                        <div className="flex gap-1 ml-auto items-center">
                                            <KeyboardShortcut command option k />
                                            <span className="text-xs opacity-75">or</span>
                                            <KeyboardShortcut command shift k />
                                        </div>
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                                <DropdownMenuItem asChild>
                                    <ButtonPrimitive menuItem onClick={toggleZenMode}>
                                        <IconExpand45 />
                                        Zen mode
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                                <ThemeMenu />
                            </DropdownMenuGroup>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
