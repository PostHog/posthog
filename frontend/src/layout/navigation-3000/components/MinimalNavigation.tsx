import { IconLogomark } from '@posthog/icons'
import { LemonButton, Popover, ProfilePicture } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AccountPopoverOverlay } from '~/layout/navigation/TopBar/AccountPopover'
import { ProjectDropdownMenu } from '~/layout/panel-layout/ProjectDropdownMenu'

export function MinimalNavigation(): JSX.Element {
    const { user } = useValues(userLogic)

    const { currentOrganization } = useValues(organizationLogic)

    const { isAccountPopoverOpen } = useValues(navigationLogic)
    const { closeAccountPopover, toggleAccountPopover } = useActions(navigationLogic)

    return (
        <nav className="flex items-center gap-2 p-2 border-b">
            <LemonButton noPadding icon={<IconLogomark className="text-3xl mx-2" />} to={urls.projectHomepage()} />
            <div className="flex items-center justify-end gap-2 flex-1">
                {currentOrganization?.teams?.length ?? 0 > 1 ? (
                    <ProjectDropdownMenu
                        buttonProps={{
                            size: 'lg',
                            className: 'h-[37px]', // Match the height of the `AccountPopoverOverlay`, remove when we redo the account
                        }}
                    />
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
            </div>
        </nav>
    )
}
