import { IconChevronRight, IconPlusSmall } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { Button } from 'lib/ui/Button/Button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { AccessLevelIndicator } from '~/layout/navigation/OrganizationSwitcher'
import { AvailableFeature } from '~/types'

export function OrganizationDropdownMenu(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button.Root>
                    <Button.Icon>
                        {currentOrganization ? (
                            <UploadedLogo
                                size="xsmall"
                                name={currentOrganization.name}
                                entityId={currentOrganization.id}
                                mediaId={currentOrganization.logo_media_id}
                            />
                        ) : (
                            <IconPlusSmall />
                        )}
                    </Button.Icon>
                    <Button.Label className="font-semibold">
                        {currentOrganization ? currentOrganization.name : 'Select organization'}
                    </Button.Label>
                    <Button.Icon size="sm">
                        <IconChevronRight className="text-secondary rotate-90 group-data-[state=open]/button-root:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                    </Button.Icon>
                </Button.Root>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="start" className="w-fit max-w-[400px]">
                <DropdownMenuLabel>Organizations</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {currentOrganization && (
                    <DropdownMenuItem asChild>
                        <Button.Root menuItem active>
                            <Button.Icon>
                                <UploadedLogo
                                    size="xsmall"
                                    name={currentOrganization.name}
                                    entityId={currentOrganization.id}
                                    mediaId={currentOrganization.logo_media_id}
                                />
                            </Button.Icon>
                            <Button.Label>{currentOrganization.name}</Button.Label>
                            <AccessLevelIndicator organization={currentOrganization} />
                        </Button.Root>
                    </DropdownMenuItem>
                )}
                {otherOrganizations.map((otherOrganization) => (
                    <DropdownMenuItem key={otherOrganization.id} asChild>
                        <Button.Root menuItem onClick={() => updateCurrentOrganization(otherOrganization.id)}>
                            <Button.Icon>
                                <UploadedLogo
                                    name={otherOrganization.name}
                                    entityId={otherOrganization.id}
                                    mediaId={otherOrganization.logo_media_id}
                                />
                            </Button.Icon>
                            <Button.Label>{otherOrganization.name}</Button.Label>
                            <Button.Icon>
                                <AccessLevelIndicator organization={otherOrganization} />
                            </Button.Icon>
                        </Button.Root>
                    </DropdownMenuItem>
                ))}
                {preflight?.can_create_org && (
                    <DropdownMenuItem asChild>
                        <Button.Root
                            menuItem
                            data-attr="new-organization-button"
                            onClick={() =>
                                guardAvailableFeature(
                                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                                    () => {
                                        closeAccountPopover()
                                        showCreateOrganizationModal()
                                    },
                                    {
                                        guardOnCloud: false,
                                    }
                                )
                            }
                        >
                            <Button.Icon>
                                <IconPlusSmall />
                            </Button.Icon>
                            <Button.Label menuItem>New organization</Button.Label>
                        </Button.Root>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
