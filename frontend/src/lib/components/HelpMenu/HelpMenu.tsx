import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import {
    IconBook,
    IconConfetti,
    IconDatabase,
    IconDownload,
    IconEllipsis,
    IconExpand45,
    IconGear,
    IconLive,
    IconOpenSidebar,
    IconQuestion,
    IconServer,
    IconShieldLock,
    IconSparkles,
    IconSupport,
} from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link/Link'
import { IconPreview } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { sidePanelOfframpLogic } from '~/layout/navigation-3000/sidepanel/sidePanelOfframpLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { appShortcutLogic } from '../AppShortcuts/appShortcutLogic'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { openCHQueriesDebugModal } from '../AppShortcuts/utils/DebugCHQueries'
import { ThemeMenu } from '../Menus/ThemeMenu'
import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { helpMenuLogic } from './helpMenuLogic'

export function HelpMenu(): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { isHelpMenuOpen } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { user } = useValues(userLogic)
    const { isCloud, preflight } = useValues(preflightLogic)
    const { showOfframpModal } = useActions(sidePanelOfframpLogic)
    const isRemovingSidePanelFlag = useFeatureFlag('UX_REMOVE_SIDEPANEL')

    return (
        <Menu.Root open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen}>
            <Menu.Trigger
                render={
                    <ButtonPrimitive
                        tooltip={
                            <>
                                Help menu
                                <RenderKeybind keybind={[keyBinds.helpMenu]} className="ml-1" />
                            </>
                        }
                        tooltipPlacement="top"
                        tooltipCloseDelayMs={0}
                        iconOnly
                        className="group"
                    >
                        <span className="flex text-secondary group-hover:text-primary">
                            <IconQuestion className="size-5" />
                        </span>
                    </ButtonPrimitive>
                }
            />
            <Menu.Portal>
                <Menu.Backdrop className="fixed inset-0 z-[var(--z-modal)]" />
                <Menu.Positioner
                    className="z-[var(--z-popover)]"
                    side="top"
                    align="start"
                    sideOffset={8}
                    collisionPadding={{ left: 0, top: 50, bottom: 50 }}
                >
                    <Menu.Popup className="primitive-menu-content max-h-[calc(var(--available-height)-4px)] min-w-[250px]">
                        <ScrollableShadows
                            direction="vertical"
                            styledScrollbars
                            className="flex flex-col gap-px overflow-x-hidden"
                            innerClassName="primitive-menu-content-inner p-1 "
                        >
                            <div className="flex flex-col gap-px">
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.ai()}
                                            buttonProps={{
                                                menuItem: true,
                                                size: 'fit',
                                                className:
                                                    'flex flex-col gap-1 p-2 border border-primary rounded h-32 items-center justify-center',
                                            }}
                                        >
                                            <span className="size-3 [&>svg]:size-4 mb-3">
                                                <IconSparkles className="text-ai" />
                                            </span>
                                            <span className="text-sm font-medium">Ask PostHog AI</span>
                                            <span className="text-xs text-tertiary text-center text-pretty">
                                                PostHog AI answers 80%+ of support questions we receive!
                                            </span>
                                        </Link>
                                    )}
                                />
                            </div>
                            <div className="flex flex-col gap-px pt-1">
                                <Menu.Item
                                    onClick={() => openSidePanel(SidePanelTab.Support)}
                                    render={
                                        <ButtonPrimitive menuItem>
                                            <IconSupport />
                                            Support
                                            <IconOpenSidebar className="size-3" />
                                        </ButtonPrimitive>
                                    }
                                />
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to="https://posthog.com/docs"
                                            buttonProps={{ menuItem: true }}
                                            target="_blank"
                                            targetBlankIcon
                                            disableDocsPanel
                                            tooltip="Open docs in new browser tab"
                                            tooltipPlacement="right"
                                        >
                                            <IconBook />
                                            Docs
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    render={(props) => (
                                        <Link {...props} to={urls.settings()} buttonProps={{ menuItem: true }}>
                                            <IconGear />
                                            Settings
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            tooltip="View your exports"
                                            tooltipPlacement="right"
                                            buttonProps={{ menuItem: true }}
                                            to={urls.exports()}
                                        >
                                            <IconDownload />
                                            Exports
                                        </Link>
                                    )}
                                />

                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            tooltip="View our changelog in new browser tab"
                                            tooltipPlacement="right"
                                            targetBlankIcon
                                            target="_blank"
                                            buttonProps={{ menuItem: true }}
                                            to="https://posthog.com/changelog"
                                        >
                                            <IconLive />
                                            Changelog
                                        </Link>
                                    )}
                                />

                                {user?.is_staff && <></>}
                                {!isCloud && (
                                    <Menu.Item
                                        render={(props) => (
                                            <Link
                                                {...props}
                                                to={urls.moveToPostHogCloud()}
                                                buttonProps={{ menuItem: true }}
                                                data-attr="top-menu-item-upgrade-to-cloud"
                                            >
                                                <IconConfetti />
                                                Try PostHog Cloud
                                            </Link>
                                        )}
                                    />
                                )}

                                {user?.is_staff && (
                                    <Menu.SubmenuRoot>
                                        <Menu.Portal>
                                            <Menu.Positioner
                                                className="z-[var(--z-popover)]"
                                                collisionPadding={{ top: 50, bottom: 50 }}
                                            >
                                                <Menu.Popup className="primitive-menu-content max-h-[calc(var(--available-height)-4px)] min-w-[250px]">
                                                    <ScrollableShadows
                                                        direction="vertical"
                                                        styledScrollbars
                                                        className="flex flex-col gap-px overflow-x-hidden"
                                                        innerClassName="primitive-menu-content-inner p-1 "
                                                    >
                                                        <Menu.Item
                                                            render={(props) => (
                                                                <Link
                                                                    {...props}
                                                                    to="/admin/"
                                                                    buttonProps={{ menuItem: true }}
                                                                    data-attr="top-menu-django-admin"
                                                                    disableClientSideRouting
                                                                >
                                                                    <IconShieldLock />
                                                                    Django admin
                                                                </Link>
                                                            )}
                                                        />
                                                        <Menu.Item
                                                            render={(props) => (
                                                                <Link
                                                                    {...props}
                                                                    to={urls.instanceStatus()}
                                                                    buttonProps={{ menuItem: true }}
                                                                    tooltip="Async migrations"
                                                                    tooltipPlacement="right"
                                                                    data-attr="top-menu-instance-panel"
                                                                >
                                                                    <IconServer />
                                                                    Instance panel
                                                                </Link>
                                                            )}
                                                        />

                                                        {user?.is_impersonated ||
                                                        preflight?.is_debug ||
                                                        preflight?.instance_preferences?.debug_queries ? (
                                                            <Menu.Item
                                                                onClick={() => {
                                                                    openCHQueriesDebugModal()
                                                                }}
                                                                render={
                                                                    <ButtonPrimitive
                                                                        menuItem
                                                                        data-attr="menu-item-debug-ch-queries"
                                                                    >
                                                                        <IconDatabase />
                                                                        Debug CH queries
                                                                        <KeyboardShortcut
                                                                            command
                                                                            option
                                                                            tab
                                                                            className="ml-auto"
                                                                        />
                                                                    </ButtonPrimitive>
                                                                }
                                                            />
                                                        ) : null}
                                                    </ScrollableShadows>
                                                </Menu.Popup>
                                            </Menu.Positioner>
                                        </Menu.Portal>
                                    </Menu.SubmenuRoot>
                                )}
                                {isRemovingSidePanelFlag && (
                                    <Menu.Item
                                        onClick={() => {
                                            showOfframpModal()
                                            setHelpMenuOpen(false)
                                        }}
                                        render={
                                            <ButtonPrimitive menuItem>
                                                <IconPreview />
                                                Show tour again <LemonTag size="small">Temporary</LemonTag>
                                            </ButtonPrimitive>
                                        }
                                    />
                                )}

                                <Menu.SubmenuRoot>
                                    <Menu.SubmenuTrigger
                                        render={
                                            <ButtonPrimitive menuItem>
                                                <IconEllipsis />
                                                More
                                                <MenuOpenIndicator intent="sub" />
                                            </ButtonPrimitive>
                                        }
                                    />
                                    <Menu.Portal>
                                        <Menu.Positioner className="z-[var(--z-popover)]">
                                            <Menu.Popup className="primitive-menu-content max-h-[calc(var(--available-height)-4px)] min-w-[250px]">
                                                <ScrollableShadows
                                                    direction="vertical"
                                                    styledScrollbars
                                                    className="flex flex-col gap-px overflow-x-hidden"
                                                    innerClassName="primitive-menu-content-inner p-1 "
                                                >
                                                    <Menu.Item
                                                        onClick={() => setAppShortcutMenuOpen(true)}
                                                        render={
                                                            <ButtonPrimitive
                                                                tooltip="Open shortcut menu"
                                                                tooltipPlacement="right"
                                                                menuItem
                                                            >
                                                                <span className="size-4 flex items-center justify-center">
                                                                    ⌘
                                                                </span>
                                                                Shortcuts
                                                                <div className="flex gap-1 ml-auto items-center">
                                                                    <KeyboardShortcut command option k />
                                                                    <span className="text-xs opacity-75">or</span>
                                                                    <KeyboardShortcut command shift k />
                                                                </div>
                                                            </ButtonPrimitive>
                                                        }
                                                    />
                                                    <Menu.Item
                                                        onClick={toggleZenMode}
                                                        render={
                                                            <ButtonPrimitive menuItem>
                                                                <IconExpand45 />
                                                                Zen mode
                                                            </ButtonPrimitive>
                                                        }
                                                    />
                                                    <ThemeMenu />
                                                </ScrollableShadows>
                                            </Menu.Popup>
                                        </Menu.Positioner>
                                    </Menu.Portal>
                                </Menu.SubmenuRoot>
                            </div>
                        </ScrollableShadows>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
