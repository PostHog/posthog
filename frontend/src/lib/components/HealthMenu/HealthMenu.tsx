import { Menu } from '@base-ui/react/menu'
import { useActions, useValues } from 'kea'

import { IconCloud, IconCode, IconDatabase, IconStethoscope, IconWarning } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link/Link'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { MenuOpenIndicator } from 'lib/ui/Menus/Menus'
import { urls } from 'scenes/urls'

import { sidePanelHealthLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import { sidePanelSdkDoctorLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSdkDoctorLogic'

import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { ScrollableShadows } from '../ScrollableShadows/ScrollableShadows'
import { healthMenuLogic } from './healthMenuLogic'

export function HealthMenu({ iconOnly = false }: { iconOnly?: boolean }): JSX.Element {
    const {
        isHealthMenuOpen,
        postHogStatus,
        postHogStatusTooltip,
        postHogStatusBadgeContent,
        postHogStatusBadgeStatus,
    } = useValues(healthMenuLogic)
    const { setHealthMenuOpen } = useActions(healthMenuLogic)
    const { needsAttention, needsUpdatingCount, sdkHealth } = useValues(sidePanelSdkDoctorLogic)
    const { issueCount: pipelineIssueCount } = useValues(sidePanelHealthLogic)

    const sdkDoctorTooltip = needsAttention
        ? 'Needs attention'
        : needsUpdatingCount > 0
          ? 'Outdated SDKs found'
          : 'SDK health is good'

    const pipelineHealthStatus = pipelineIssueCount > 0 ? 'danger' : 'success'

    const pipelineStatusTooltip =
        pipelineIssueCount > 0
            ? `${pipelineIssueCount} pipeline issue${pipelineIssueCount === 1 ? '' : 's'}`
            : 'All pipelines healthy'

    // Cumulative badge content and status
    const triggerBadgeContent =
        postHogStatus !== 'operational' || needsAttention || needsUpdatingCount > 0 || pipelineIssueCount > 0
            ? '!'
            : '✓'
    const triggerBadgeStatus =
        postHogStatus !== 'operational' || needsAttention || needsUpdatingCount > 0 || pipelineIssueCount > 0
            ? 'danger'
            : 'success'

    return (
        <Menu.Root open={isHealthMenuOpen} onOpenChange={setHealthMenuOpen}>
            <Menu.Trigger
                render={
                    <ButtonPrimitive
                        tooltip={
                            !iconOnly ? (
                                <>
                                    Health menu
                                    <RenderKeybind keybind={[keyBinds.healthMenu]} className="ml-1" />
                                </>
                            ) : undefined
                        }
                        tooltipPlacement="right"
                        tooltipCloseDelayMs={0}
                        iconOnly={iconOnly}
                        className="group"
                        menuItem={!iconOnly}
                    >
                        <span className="flex text-secondary group-hover:text-primary">
                            <IconWithBadge size="xsmall" content={triggerBadgeContent} status={triggerBadgeStatus}>
                                <IconStethoscope className="size-4.5" />
                            </IconWithBadge>
                        </span>
                        {!iconOnly && (
                            <>
                                <span className="-ml-[2px]">Health</span>
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
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.health()}
                                            buttonProps={{
                                                menuItem: true,
                                                size: 'fit',
                                                className:
                                                    'flex flex-col gap-1 p-2 border border-primary rounded h-32 items-center justify-center',
                                            }}
                                        >
                                            <IconStethoscope className="size-5" />
                                            <span className="text-sm font-medium">View health overview</span>
                                            <span className="text-xs text-tertiary text-center text-pretty">
                                                See at-a-glance view of the health of your project.{' '}
                                            </span>
                                        </Link>
                                    )}
                                />
                            </div>
                            <div className="flex flex-col gap-px pt-1">
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            targetBlankIcon
                                            target="_blank"
                                            buttonProps={{ menuItem: true }}
                                            to="https://posthogstatus.com"
                                            tooltip={postHogStatusTooltip}
                                            tooltipPlacement="right"
                                            tooltipCloseDelayMs={0}
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
                                            to={urls.sdkDoctor()}
                                            buttonProps={{ menuItem: true }}
                                            tooltip={sdkDoctorTooltip}
                                            tooltipPlacement="right"
                                            tooltipCloseDelayMs={0}
                                        >
                                            <IconWithBadge
                                                size="xsmall"
                                                content={needsUpdatingCount > 0 ? '!' : '✓'}
                                                status={sdkHealth}
                                            >
                                                <IconCode className="size-5" />
                                            </IconWithBadge>
                                            SDK Doctor
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    render={(props) => (
                                        <Link
                                            {...props}
                                            to={urls.pipelineStatus()}
                                            buttonProps={{ menuItem: true }}
                                            tooltip={pipelineStatusTooltip}
                                            tooltipPlacement="right"
                                            tooltipCloseDelayMs={0}
                                        >
                                            <IconWithBadge
                                                size="xsmall"
                                                content={pipelineIssueCount > 0 ? '!' : '✓'}
                                                status={pipelineHealthStatus}
                                            >
                                                <IconDatabase className="size-5" />
                                            </IconWithBadge>
                                            Pipeline status
                                        </Link>
                                    )}
                                />
                                <Menu.Item
                                    render={(props) => (
                                        <Link {...props} to={urls.ingestionWarnings()} buttonProps={{ menuItem: true }}>
                                            <IconWarning className="size-5" />
                                            Ingestion warnings
                                        </Link>
                                    )}
                                />
                            </div>
                        </ScrollableShadows>
                    </Menu.Popup>
                </Menu.Positioner>
            </Menu.Portal>
        </Menu.Root>
    )
}
