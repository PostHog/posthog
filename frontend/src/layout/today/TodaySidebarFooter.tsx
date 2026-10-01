import { useValues } from 'kea'
import { ComponentProps } from 'react'

import { IconChevronDown, IconGear } from '@posthog/icons'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { pendingInvitesLogic } from 'lib/components/Account/pendingInvitesLogic'
import { PendingInviteDot } from 'lib/components/Account/ProjectMenu'
import { Link } from 'lib/lemon-ui/Link'
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
    const projectName = currentTeam?.name ?? 'Project'

    const renderTrigger = (props: ComponentProps<'button'>): JSX.Element => (
        <button {...props} type="button" className="TodaySidebarFooter__project" data-attr="today-project-menu">
            <UploadedLogo
                name={currentOrganization?.name ?? '?'}
                entityId={currentOrganization?.id ?? ''}
                mediaId={currentOrganization?.logo_media_id ?? ''}
            />
            <span className="TodaySidebarFooter__projectText">
                <small>{currentOrganization?.name ?? 'Organization'}</small>
                <strong>{projectName}</strong>
            </span>
            {pendingInvites.length > 0 && <PendingInviteDot />}
            <IconChevronDown />
        </button>
    )

    return (
        <div className="TodaySidebarFooter">
            {sidebarVisible ? <NewAccountMenu side="top" renderTrigger={renderTrigger} /> : renderTrigger({})}
            <Link
                to={urls.settings('project')}
                className="TodaySidebarFooter__settings"
                data-attr="today-settings"
                subtle
            >
                <IconGear />
                <span>Settings</span>
            </Link>
        </div>
    )
}
