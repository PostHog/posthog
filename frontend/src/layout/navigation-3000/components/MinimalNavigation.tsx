import { useActions, useValues } from 'kea'

import { IconLogomark } from '@posthog/icons'
import { LemonButton, Lettermark, Popover, ProfilePicture } from '@posthog/lemon-ui'

import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ProjectSwitcherOverlay } from '~/layout/navigation/ProjectSwitcher'
import { AccountPopoverOverlay } from '~/layout/navigation/TopBar/AccountPopover'
import { navigationLogic } from '~/layout/navigation/navigationLogic'

export function MinimalNavigation(): JSX.Element {
    const { user } = useValues(userLogic)

    const { currentTeam } = useValues(teamLogic)
    const { currentOrganization } = useValues(organizationLogic)

    const { isAccountPopoverOpen, isProjectSwitcherShown } = useValues(navigationLogic)
    const { closeAccountPopover, toggleAccountPopover, toggleProjectSwitcher, hideProjectSwitcher } =
        useActions(navigationLogic)

    return (
        <nav className="flex items-center justify-between gap-2 border-b p-2">
            <LemonButton noPadding icon={<IconLogomark className="mx-2 text-3xl" />} to={urls.projectHomepage()} />
            <div className="flex-1" />
            {(currentOrganization?.teams?.length ?? 0 > 1) ? (
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
