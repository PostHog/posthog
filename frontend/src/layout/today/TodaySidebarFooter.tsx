import { useValues } from 'kea'
import { ComponentProps } from 'react'

import { IconGear } from '@posthog/icons'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { todayShellLogic } from './todayShellLogic'

export function TodaySidebarFooter(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { pendingInvites } = useValues(pendingInvitesLogic)
    const { sidebarVisible } = useValues(todayShellLogic)

    const renderTrigger = (props: ComponentProps<'button'>): JSX.Element => (
        <Button
            {...props}
            size="lg"
            className="TodaySidebarFooter__account justify-start"
            data-attr="today-project-menu"
        >
            <UploadedLogo
                name={currentOrganization?.name ?? '?'}
                entityId={currentOrganization?.id ?? ''}
                mediaId={currentOrganization?.logo_media_id ?? ''}
                size="small"
            />
            <span className="TodaySidebarFooter__name">{currentTeam?.name ?? 'Project'}</span>
            {pendingInvites.length > 0 && <PendingInviteDot className="ml-auto" />}
        </Button>
    )

    return (
        <div className="TodaySidebarFooter">
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
                            className="TodaySidebarFooter__settings"
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
    )
}
