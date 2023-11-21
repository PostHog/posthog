import { LemonButton, Lettermark, Popover, ProfilePicture } from '@posthog/lemon-ui'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { SitePopoverOverlay } from '~/layout/navigation/TopBar/SitePopover'
import { useValues, useActions } from 'kea'
import { teamLogic } from 'scenes/teamLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { userLogic } from 'scenes/userLogic'
import { IconLogomark } from '@posthog/icons'
import { urls } from 'scenes/urls'
import { organizationLogic } from 'scenes/organizationLogic'

export function MinimalNavigation(): JSX.Element {
    const { user } = useValues(userLogic)

    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const { isSitePopoverOpen, isProjectSwitcherShown } = useValues(navigationLogic)
    const { closeSitePopover, toggleSitePopover, toggleProjectSwitcher, hideProjectSwitcher } =
        useActions(navigationLogic)

    return (
        <nav className="flex items-center justify-between gap-2 p-2 border-b">
            <span className="flex-1">
                <LemonButton icon={<IconLogomark className="text-2xl" />} to={urls.projectHomepage()} />
            </span>
            {currentOrganization?.teams?.length ?? 0 > 1 ? (
                <Popover
                    overlay={<ProjectSwitcherOverlay onClickInside={hideProjectSwitcher} />}
                    visible={isProjectSwitcherShown}
                    onClickOutside={hideProjectSwitcher}
                    placement="right-start"
                >
                    <LemonButton
                        type="tertiary"
                        status="muted"
                        icon={<Lettermark name={currentTeam?.name} />}
                        onClick={toggleProjectSwitcher}
                    >
                        {currentTeam?.name ?? 'Current project'}
                    </LemonButton>
                </Popover>
            ) : null}
            <Popover
                overlay={<SitePopoverOverlay />}
                visible={isSitePopoverOpen}
                onClickOutside={closeSitePopover}
                placement="right-end"
            >
                <LemonButton
                    type="tertiary"
                    status="muted"
                    icon={<ProfilePicture name={user?.first_name} email={user?.email} size="md" />}
                    onClick={toggleSitePopover}
                >
                    {user?.first_name || user?.email}
                </LemonButton>
            </Popover>
        </nav>
    )
}
