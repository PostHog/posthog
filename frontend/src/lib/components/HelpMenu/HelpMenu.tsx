import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import { IconCopy, IconDatabase, IconOpenSidebar, IconServer, IconShieldLock, IconSparkles } from '@posthog/icons'
import { ProfilePicture } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/components/KeyboardShortcut/KeyboardShortcut'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconMenu, IconWithBadge } from 'lib/lemon-ui/icons'
import { LemonBadge } from 'lib/lemon-ui/LemonBadge/LemonBadge'
import { Link } from 'lib/lemon-ui/Link/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Label } from 'lib/ui/Label/Label'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { RenderKeybind } from '../Shortcuts/ShortcutMenu'
import { keyBinds } from '../Shortcuts/shortcuts'
import { openCHQueriesDebugModal } from '../Shortcuts/utils/DebugCHQueries'
import { healthSummaryLogic } from './healthSummaryLogic'
import { helpMenuLogic } from './helpMenuLogic'
import { IconCheeseburger } from './IconCheeseburger'
import { posthogStatusLogic } from './posthogStatusLogic'

export function HelpMenu({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { isHelpMenuOpen, triggerBadgeContent, triggerBadgeStatus } = useValues(helpMenuLogic)
    const { setHelpMenuOpen } = useActions(helpMenuLogic)
    const { user } = useValues(userLogic)
    const { isCloudOrDev, preflight } = useValues(preflightLogic)
    const { reportAccountOwnerClicked } = useActions(eventUsageLogic)
    const { billing } = useValues(billingLogic)
    const { postHogStatusTooltip, postHogStatusBadgeStatus, postHogStatusBadgeContent, statusPageUrl } =
        useValues(posthogStatusLogic)
    const { totalIssues } = useValues(healthSummaryLogic)

    // A/B test of the trigger icon: control = 3-line hamburger menu icon, test = cheeseburger glyph
    const useCheeseburger = useFeatureFlag('MORE_MENU_ICON_EXPERIMENT', 'test')

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
                        data-attr="help-menu-button"
                    >
                        <span className="flex text-secondary group-hover:text-primary">
                            <IconWithBadge
                                content={triggerBadgeContent}
                                size="xsmall"
                                status={triggerBadgeStatus}
                                className="flex"
                            >
                                {useCheeseburger ? (
                                    <IconCheeseburger className="size-[17px]" />
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
                                            data-attr="more-menu-ask-ai-button"
                                        >
                                            Ask PostHog AI
                                            <IconSparkles className="text-ai" />
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    onClick={() => openSidePanel(SidePanelTab.Support)}
                                    render={
                                        <ButtonPrimitive menuItem data-attr="more-menu-support-button">
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
                                            data-attr="more-menu-docs-button"
                                        >
                                            Docs
                                        </Link>
                                    )}
                                />

                                <Label intent="menu" className="px-2 mt-3">
                                    System
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
                                            data-attr="more-menu-status-button"
                                        >
                                            Status Page
                                            {postHogStatusBadgeStatus !== 'success' && (
                                                <LemonBadge
                                                    content={postHogStatusBadgeContent}
                                                    size="xsmall"
                                                    status={postHogStatusBadgeStatus}
                                                />
                                            )}
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
                                            data-attr="more-menu-health-button"
                                        >
                                            Health
                                            <LemonBadge
                                                size="small"
                                                content={triggerBadgeContent}
                                                status={triggerBadgeStatus}
                                            />
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
                                            data-attr="more-menu-changelog-button"
                                        >
                                            Changelog
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
                                            Exports
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

                                {billing?.account_owner?.email && billing?.account_owner?.name && (
                                    <>
                                        <Label intent="menu" className="px-2 mt-4">
                                            YOUR POSTHOG HUMAN
                                        </Label>
                                        <Menu.Item
                                            onClick={() => {
                                                // It's dumb rechecking this, but TS needs it because of closures
                                                if (!billing?.account_owner?.email || !billing?.account_owner?.name) {
                                                    return
                                                }

                                                void copyToClipboard(billing.account_owner.email, 'email')
                                                reportAccountOwnerClicked({
                                                    name: billing.account_owner.name,
                                                    email: billing.account_owner.email,
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
                                                            first_name: billing.account_owner.name,
                                                            email: billing.account_owner.email,
                                                        }}
                                                        size="xs"
                                                    />
                                                    <span className="truncate font-semibold">
                                                        {billing.account_owner.name}
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
