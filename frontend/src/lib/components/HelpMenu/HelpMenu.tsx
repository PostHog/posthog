import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import {
    IconBook,
    IconCloud,
    IconConfetti,
    IconCopy,
    IconDatabase,
    IconEllipsis,
    IconExpand45,
    IconHeart,
    IconLive,
    IconOpenSidebar,
    IconServer,
    IconShieldLock,
    IconSparkles,
    IconStethoscope,
} from '@posthog/icons'
import { ProfilePicture } from '@posthog/lemon-ui'

import { IconWithBadge } from 'lib/lemon-ui/icons'
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

import { SidePanelQuestionIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelQuestionIcon'
import { SidePanelSupportIcon } from 'products/conversations/frontend/components/SidePanel/SidePanelSupportIcon'

import { appShortcutLogic } from '../AppShortcuts/appShortcutLogic'
import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { openCHQueriesDebugModal } from '../AppShortcuts/utils/DebugCHQueries'
import { ThemeMenu } from '../Menus/ThemeMenu'
import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { healthSummaryLogic } from './healthSummaryLogic'
import { helpMenuLogic } from './helpMenuLogic'
import { posthogStatusLogic } from './posthogStatusLogic'

export function HelpMenu({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { isHelpMenuOpen, triggerBadgeContent, triggerBadgeStatus } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { toggleZenMode } = useActions(navigation3000Logic)
    const { setAppShortcutMenuOpen } = useActions(appShortcutLogic)
    const { user } = useValues(userLogic)
    const { isCloudOrDev, preflight } = useValues(preflightLogic)
    const { reportAccountOwnerClicked } = useActions(eventUsageLogic)
    const { billing } = useValues(billingLogic)
    const { postHogStatusTooltip, postHogStatusBadgeStatus, postHogStatusBadgeContent, statusPageUrl } =
        useValues(posthogStatusLogic)
    const { totalIssues } = useValues(healthSummaryLogic)

    return (
        <Menu.Root open={isHelpMenuOpen} onOpenChange={setHelpMenuOpen}>
            <Menu.Trigger
                render={
                    <ButtonPrimitive
                        tooltip={
                            iconOnly ? (
                                <>
                                    Help menu
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
                        data-attr="help-menu-button"
                    >
                        <span className="flex text-secondary group-hover:text-primary">
                            <IconWithBadge
                                content={triggerBadgeContent}
                                size="xsmall"
                                status={triggerBadgeStatus}
                                className="flex"
                            >
                                <SidePanelQuestionIcon className="size-[17px]" />
                            </IconWithBadge>
                        </span>
                        {!iconOnly && (
                            <>
                                <span className="-ml-px">Help</span>
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
                            <div className="flex flex-col gap-px mb-2">
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.ai()}
                                            buttonProps={{
                                                menuItem: true,
                                                size: 'fit',
                                                className:
                                                    'flex flex-col gap-1 p-2 border border-primary rounded h-32 items-center justify-center shadow hover:border-accent transition-colors',
                                            }}
                                            data-attr="help-menu-ask-posthog-ai-button"
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
                                            PostHog status
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
                                            Health issues
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

                                <Menu.SubmenuRoot>
                                    <Menu.SubmenuTrigger
                                        render={
                                            <ButtonPrimitive menuItem data-attr="help-menu-display-options-button">
                                                <IconEllipsis />
                                                Display options
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
                                                                data-attr="help-menu-shortcuts-button"
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
                                                            <ButtonPrimitive
                                                                menuItem
                                                                data-attr="help-menu-zen-mode-button"
                                                            >
                                                                <IconExpand45 />
                                                                Zen mode
                                                                <div className="flex gap-1 ml-auto items-center">
                                                                    <KeyboardShortcut command option z />
                                                                </div>
                                                            </ButtonPrimitive>
                                                        }
                                                    />
                                                    <ThemeMenu />
                                                </ScrollableShadows>
                                            </Menu.Popup>
                                        </Menu.Positioner>
                                    </Menu.Portal>
                                </Menu.SubmenuRoot>

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
