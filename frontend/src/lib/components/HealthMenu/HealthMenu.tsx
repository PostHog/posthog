import { useActions, useValues } from 'kea'

import { IconCloud, IconCode, IconDatabase, IconStethoscope, IconWarning } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link/Link'
import { IconWithBadge } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { sidePanelHealthLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import { sidePanelSdkDoctorLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSdkDoctorLogic'

import { RenderKeybind } from '../AppShortcuts/AppShortcutMenu'
import { keyBinds } from '../AppShortcuts/shortcuts'
import { healthMenuLogic } from './healthMenuLogic'

export function HealthMenu(): JSX.Element {
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
        <DropdownMenu open={isHealthMenuOpen} onOpenChange={setHealthMenuOpen}>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive
                    tooltip={
                        <>
                            Health menu
                            <RenderKeybind keybind={[keyBinds.healthMenu]} className="ml-1" />
                        </>
                    }
                    tooltipPlacement="top"
                    tooltipCloseDelayMs={0}
                    iconOnly
                    className="group"
                >
                    <span className="flex text-secondary group-hover:text-primary">
                        <IconWithBadge size="xsmall" content={triggerBadgeContent} status={triggerBadgeStatus}>
                            {/* Heart Plus Icon TODO: add this to icons */}
                            <IconStethoscope className="size-4.5" />
                        </IconWithBadge>
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
                                <LemonTag type="warning" className="my-1" size="small">
                                    posthog only
                                </LemonTag>
                            </span>
                        </Link>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
                <DropdownMenuGroup className="flex flex-col gap-px pt-0">
                    <DropdownMenuItem asChild>
                        <Link
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
                    </DropdownMenuItem>

                    <DropdownMenuItem asChild>
                        <Link
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
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link
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
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <Link to={urls.ingestionWarnings()} buttonProps={{ menuItem: true }}>
                            <IconWarning className="size-5" />
                            Ingestion warnings
                        </Link>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
