import { IconLogomark } from '@posthog/icons'
import { LemonButton, Lettermark, Popover, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { AccountPopoverOverlay } from '~/layout/navigation/TopBar/AccountPopover'

export function MinimalNavigation(): JSX.Element {
    const { user } = useValues(userLogic)

    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const { isAccountPopoverOpen, isProjectSwitcherShown } = useValues(navigationLogic)
    const { closeAccountPopover, toggleAccountPopover, toggleProjectSwitcher, hideProjectSwitcher } =
        useActions(navigationLogic)

    return (
        <nav className="flex items-center justify-between gap-2 p-2 border-b">
            <span className="flex-1">
                <LemonButton noPadding icon={<IconLogomark className="text-3xl" />} to={urls.projectHomepage()} />
            </span>
            {currentOrganization?.teams?.length ?? 0 > 1 ? (
                <Popover
                    overlay={<ProjectSwitcherOverlay onClickInside={hideProjectSwitcher} />}
                    visible={isProjectSwitcherShown}
                    onClickOutside={hideProjectSwitcher}
                    placement="bottom"
                >
                    <LemonButton
                        type="tertiary"
                        icon={<Lettermark name={currentTeam?.name} />}
                        onClick={toggleProjectSwitcher}
                    >
                        {currentTeam?.name ?? 'Current project'}
                    </LemonButton>
                </Popover>
            ) : null}
            <Popover
                overlay={<AccountPopoverOverlay />}
                visible={isAccountPopoverOpen}
                onClickOutside={closeAccountPopover}
                placement="bottom"
            >
                <LemonButton
                    type="tertiary"
                    icon={<ProfilePicture user={user} size="md" />}
                    onClick={toggleAccountPopover}
                >
                    {user?.first_name || user?.email}
                </LemonButton>
            </Popover>
        </nav>
    )
}
