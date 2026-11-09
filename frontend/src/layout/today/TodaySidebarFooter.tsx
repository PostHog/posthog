import { useValues } from 'kea'
import { ComponentProps } from 'react'

import { IconGear } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger, cn } from '@posthog/quill'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { NavSwitchButtons } from 'lib/components/NavSwitch/NavSwitch'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { todayShellLogic } from './todayShellLogic'

const TRIGGER_CLASSES = 'text-muted-foreground hover:text-foreground data-[popup-open]:text-foreground'

export function TodaySidebarFooter(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const { sidebarVisible } = useValues(todayShellLogic)

    const renderTrigger = (props: ComponentProps<'button'>): JSX.Element => (
        <Button
            {...props}
            size="lg"
            className={cn(TRIGGER_CLASSES, 'min-w-0 justify-start ps-1.5 pe-2')}
            data-attr="today-project-menu"
        >
            <UploadedLogo
                name={currentOrganization?.name ?? '?'}
                entityId={currentOrganization?.id ?? ''}
                mediaId={currentOrganization?.logo_media_id ?? ''}
                size="small"
            />
            <span className="min-w-0 truncate">{currentTeam?.name ?? 'Project'}</span>
            {pendingInvites.length > 0 && <PendingInviteDot className="ml-auto" />}
        </Button>
    )

    return (
        <div className="flex-none border-t border-[var(--border)]">
            {/* The old navigation's sidebar footer holds the same buttons, so they sit in the same place either way. */}
            <div className="px-2 pt-2">
                <NavSwitchButtons surface="today_sidebar" />
            </div>
            <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-1 px-2 pt-2 pb-2">
                {sidebarVisible ? (
                    <NewAccountMenu side="top" align="start" sideOffset={12} renderTrigger={renderTrigger} />
                ) : (
                    renderTrigger({})
                )}
                <Tooltip>
                    <TooltipTrigger
                        delay={0}
                        render={
                            <Button
                                size="icon-lg"
                                className={TRIGGER_CLASSES}
                                aria-label="Settings"
                                nativeButton={false}
                                render={<LinkPrimitive to={urls.settings('project')} />}
                                data-attr="today-settings"
                            />
                        }
                    >
                        <IconGear className="size-4.5" />
                    </TooltipTrigger>
                    <TooltipContent>Settings</TooltipContent>
                </Tooltip>
            </div>
        </div>
    )
}
