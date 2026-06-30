import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import {
    IconBook,
    IconCloud,
    IconConfetti,
    IconCopy,
    IconDatabase,
    IconDownload,
    IconExpand45,
    IconGear,
    IconHeart,
    IconLive,
    IconOpenSidebar,
    IconServer,
    IconShieldLock,
    IconSparkles,
    IconStethoscope,
} from '@posthog/icons'
import { ProfilePicture } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconMenu, IconWithBadge } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { Label } from 'lib/ui/Label/Label'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { KeyboardShortcut } from '~/layout/navigation-3000/components/KeyboardShortcut'
import { navigation3000Logic } from '~/layout/navigation-3000/navigationLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { SidePanelSupportIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelSupportIcon'

import { ThemeMenu } from '../Menus/ThemeMenu'
import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { shortcutLogic } from '../Shortcuts/shortcutLogic'
import { RenderKeybind } from '../Shortcuts/ShortcutMenu'
import { keyBinds } from '../Shortcuts/shortcuts'
import { openCHQueriesDebugModal } from '../Shortcuts/utils/DebugCHQueries'
import { healthSummaryLogic } from './healthSummaryLogic'
import { helpMenuLogic } from './helpMenuLogic'
import { posthogStatusLogic } from './posthogStatusLogic'

export function HelpMenu({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { isHelpMenuOpen, triggerBadgeContent, triggerBadgeStatus } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { setShortcutMenuOpen } = useActions(shortcutLogic)
    const { user } = useValues(userLogic)
    const { isCloudOrDev, preflight } = useValues(preflightLogic)
    const { reportAccountOwnerClicked } = useActions(eventUsageLogic)
    const { billing } = useValues(billingLogic)
    const { postHogStatusTooltip, postHogStatusBadgeStatus, postHogStatusBadgeContent, statusPageUrl } =
        useValues(posthogStatusLogic)
    const { totalIssues } = useValues(healthSummaryLogic)

    // A/B test of the trigger icon: control = 3-line hamburger menu icon, test = burger glyph
    const useBurgerGlyph = useFeatureFlag('MORE_MENU_ICON_EXPERIMENT', 'test')

    return (
        <Menu.Root open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen}>
            <Menu.Trigger
                render={
                    <ButtonPrimitive
                        tooltip={
                            iconOnly ? (
                                <>
                                    More
                                    <RenderKeybind keybind={[keyBinds.helpMenu]} className="ml-1" />
                                </>
                            ) : undefined
                        }
                        tooltipPlacement="right"
                        tooltipCloseDelayMs={0}
                        iconOnly={iconOnly}
                        className="group"
                        menuItem={!iconOnly}
                        fullWidth={iconOnly}
                        data-attr="more-menu-button"
                    >
                        <span className="flex text-secondary group-hover:text-primary">
                            <IconWithBadge
                                content={triggerBadgeContent}
                                size="xsmall"
                                status={triggerBadgeStatus}
                                className="flex"
                            >
                                {useBurgerGlyph ? (
                                    <svg
                                        className="size-[17px]"
                                        viewBox="0 0 24 24"
                                        fill="currentColor"
                                        xmlns="http://www.w3.org/2000/svg"
                                        aria-hidden
                                    >
                                        <path d="M6.08892 4.86669C8.09973 4.21897 10.4602 4 12 4C13.5398 4 15.9003 4.21897 17.9111 4.86669C18.9138 5.18967 19.9017 5.64179 20.6564 6.28456C21.4307 6.94413 22 7.84629 22 9C22 9.55228 21.5523 10 21 10H3C2.44772 10 2 9.55228 2 9C2 7.84629 2.56929 6.94413 3.34365 6.28456C4.09829 5.64179 5.08623 5.18967 6.08892 4.86669Z" />
                                        <path d="M4.88462 13.5481C5.59846 13.2506 6.40154 13.2506 7.11539 13.5481C8.32154 14.0506 9.67846 14.0506 10.8846 13.5481C11.5985 13.2506 12.4015 13.2506 13.1154 13.5481C14.3215 14.0506 15.6785 14.0506 16.8846 13.5481C17.5985 13.2506 18.4015 13.2506 19.1154 13.5481C19.7183 13.7993 20.3589 13.9249 20.9994 13.925C21.5517 13.9251 21.9994 13.4774 21.9995 12.9251C21.9996 12.3728 21.5519 11.9251 20.9996 11.925C20.6205 11.925 20.2414 11.8506 19.8846 11.7019C18.6785 11.1994 17.3215 11.1994 16.1154 11.7019C15.4015 11.9994 14.5985 11.9994 13.8846 11.7019C12.6785 11.1994 11.3215 11.1994 10.1154 11.7019C9.40154 11.9994 8.59846 11.9994 7.88462 11.7019C6.67846 11.1994 5.32154 11.1994 4.11539 11.7019C3.75845 11.8506 3.37928 11.925 3 11.925C2.44772 11.925 2 12.3727 2 12.925C2 13.4773 2.44772 13.925 3 13.925C3.64072 13.925 4.28155 13.7994 4.88462 13.5481Z" />
                                        <path d="M18.032 20C18.4706 20 18.8491 20 19.1624 19.9787C19.4922 19.9561 19.8221 19.9066 20.1481 19.7716C20.8831 19.4672 21.4672 18.8831 21.7716 18.1481C21.9066 17.8221 21.9561 17.4922 21.9787 17.1624C22 16.8491 22 16.4706 22 16.032V16C22 15.4477 21.5523 15 21 15H3C2.44772 15 2 15.4477 2 16V16.032C1.99999 16.4706 1.99998 16.8491 2.02135 17.1624C2.04386 17.4922 2.09336 17.8221 2.22836 18.1481C2.53284 18.8831 3.11687 19.4672 3.85195 19.7716C4.17788 19.9066 4.50779 19.9561 4.83762 19.9787C5.15087 20 5.52934 20 5.96798 20H18.032Z" />
                                    </svg>
                                ) : (
                                    <IconMenu className="size-[17px]" />
                                )}
                            </IconWithBadge>
                        </span>
                        {!iconOnly && (
                            <>
                                <span className="-ml-px">More</span>
                                <MenuOpenIndicator direction="up" />
                            </>
                        )}
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
                                <Label intent="menu" className="px-2">
                                    Help
                                </Label>
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.ai()}
                                            buttonProps={{ menuItem: true }}
                                            data-attr="help-menu-ask-posthog-ai-button"
                                        >
                                            <IconSparkles className="text-ai" />
                                            Ask PostHog AI
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    onClick={() => openSidePanel(SidePanelTab.Support)}
                                    render={
                                        <ButtonPrimitive menuItem data-attr="help-menu-support-button">
                                            <SidePanelSupportIcon />
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
                                            data-attr="help-menu-docs-button"
                                        >
                                            <IconBook />
                                            Docs
                                        </Link>
                                    )}
                                />

                                <Label intent="menu" className="px-2 mt-2">
                                    Project
                                </Label>
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.settings('project')}
                                            buttonProps={{ menuItem: true }}
                                            data-attr="more-menu-settings-button"
                                        >
                                            <IconGear />
                                            Settings
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.exports()}
                                            buttonProps={{ menuItem: true }}
                                            data-attr="more-menu-exports-button"
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
                                            to={urls.health()}
                                            buttonProps={{ menuItem: true }}
                                            tooltip={
                                                totalIssues > 0
                                                    ? `${totalIssues} health issue${totalIssues === 1 ? '' : 's'}`
                                                    : 'All systems healthy'
                                            }
                                            tooltipPlacement="right"
                                            tooltipCloseDelayMs={0}
                                            data-attr="help-menu-health-issues-button"
                                        >
                                            <IconWithBadge
                                                size="xsmall"
                                                content={triggerBadgeContent}
                                                status={triggerBadgeStatus}
                                            >
                                                <IconStethoscope />
                                            </IconWithBadge>
                                            Health
                                        </Link>
                                    )}
                                />

                                <Label intent="menu" className="px-2 mt-2">
                                    PostHog
                                </Label>
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            targetBlankIcon
                                            target="_blank"
                                            buttonProps={{ menuItem: true }}
                                            to={statusPageUrl}
                                            tooltip={postHogStatusTooltip}
                                            tooltipPlacement="right"
                                            tooltipCloseDelayMs={0}
                                            data-attr="help-menu-posthog-status-button"
                                        >
                                            <IconWithBadge
                                                content={postHogStatusBadgeContent}
                                                size="xsmall"
                                                status={postHogStatusBadgeStatus}
                                                className="flex"
                                            >
                                                <IconCloud />
                                            </IconWithBadge>
                                            Status
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
                                            data-attr="help-menu-changelog-button"
                                        >
                                            <IconLive />
                                            Changelog
                                        </Link>
                                    )}
                                />

                                {!isCloudOrDev && (
                                    <Menu.Item
                                        render={(props) => (
                                            <Link
                                                {...props}
                                                to={urls.moveToPostHogCloud()}
                                                buttonProps={{ menuItem: true }}
                                                data-attr="help-menu-upgrade-to-cloud-button"
                                            >
                                                <IconConfetti />
                                                Try PostHog Cloud
                                            </Link>
                                        )}
                                    />
                                )}

                                {user?.is_staff && (
                                    <Menu.SubmenuRoot>
                                        <Menu.SubmenuTrigger
                                            render={
                                                <ButtonPrimitive menuItem data-attr="help-menu-admin-button">
                                                    <IconHeart />
                                                    Admin (Lucky you!)
                                                    <MenuOpenIndicator intent="sub" />
                                                </ButtonPrimitive>
                                            }
                                        />
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
                                                                    data-attr="help-menu-django-admin-button"
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
                                                                    data-attr="help-menu-instance-panel-button"
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
                                                                        data-attr="help-menu-debug-ch-queries-button"
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

                                <Label intent="menu" className="px-2 mt-2">
                                    More
                                </Label>
                                <Menu.Item
                                    onClick={() => setShortcutMenuOpen(true)}
                                    render={
                                        <ButtonPrimitive
                                            tooltip="Open shortcut menu"
                                            tooltipPlacement="right"
                                            menuItem
                                            data-attr="help-menu-shortcuts-button"
                                        >
                                            <span className="size-4 flex items-center justify-center">⌘</span>
                                            Shortcuts
                                            <div className="flex gap-1 ml-auto items-center">
                                                <KeyboardShortcut command option k />
                                                <span className="text-xs opacity-75">or</span>
                                                <KeyboardShortcut command shift k />
                                            </div>
                                        </ButtonPrimitive>
                                    }
                                />
                                <ThemeMenu />
                                <Menu.Item
                                    onClick={toggleZenMode}
                                    render={
                                        <ButtonPrimitive menuItem data-attr="help-menu-zen-mode-button">
                                            <IconExpand45 />
                                            Zen mode
                                            <div className="flex gap-1 ml-auto items-center">
                                                <KeyboardShortcut command option z />
                                            </div>
                                        </ButtonPrimitive>
                                    }
                                />

                                {billing?.account_owner?.email && billing?.account_owner?.name && (
                                    <>
                                        <Label intent="menu" className="px-2 mt-2">
                                            YOUR POSTHOG HUMAN
                                        </Label>
                                        <DropdownMenuSeparator />
                                        <Menu.Item
                                            onClick={() => {
                                                void copyToClipboard(billing?.account_owner?.email || '', 'email')
                                                reportAccountOwnerClicked({
                                                    name: billing?.account_owner?.name || '',
                                                    email: billing?.account_owner?.email || '',
                                                })
                                            }}
                                            render={
                                                <ButtonPrimitive
                                                    menuItem
                                                    tooltip="This is your dedicated PostHog human. Click to copy their email. They can help you with trying out new products, solving problems, and reducing your spend."
                                                    tooltipPlacement="right"
                                                    data-attr="help-menu-account-owner-button"
                                                >
                                                    <ProfilePicture
                                                        user={{
                                                            first_name: billing?.account_owner?.name || '',
                                                            email: billing?.account_owner?.email || '',
                                                        }}
                                                        size="xs"
                                                    />
                                                    <span className="truncate font-semibold">
                                                        {billing?.account_owner?.name || ''}
                                                    </span>
                                                    <div className="ml-auto">
                                                        <IconCopy />
                                                    </div>
                                                </ButtonPrimitive>
                                            }
                                        />
                                    </>
                                )}
                            </div>
                        </ScrollableShadows>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
