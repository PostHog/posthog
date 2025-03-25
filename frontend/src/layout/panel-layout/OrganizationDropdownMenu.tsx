import { IconChevronRight, IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { IconWrapper } from 'lib/ui/IconWrapper/IconWrapper'
import { cn } from 'lib/utils/css-classes'
import { useState } from 'react'
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

    const [isDropdownOpen, setIsDropdownOpen] = useState(false)

    return (
        <DropdownMenu
            onOpenChange={(open) => {
                setIsDropdownOpen(open)
            }}
        >
            <DropdownMenuTrigger asChild>
                <LemonButton
                    icon={
                        currentOrganization ? (
                            <UploadedLogo
                                name={currentOrganization.name}
                                entityId={currentOrganization.id}
                                mediaId={currentOrganization.logo_media_id}
                            />
                        ) : (
                            <IconWrapper>
                                <IconPlusSmall />
                            </IconWrapper>
                        )
                    }
                    type="tertiary"
                    size="small"
                    className="w-fit"
                    tooltip="Open organization dropdown"
                    sideIcon={
                        <IconWrapper size="sm">
                            <IconChevronRight
                                className={cn(
                                    'transition-transform duration-200 prefers-reduced-motion:transition-none',
                                    isDropdownOpen ? 'rotate-270' : 'rotate-90'
                                )}
                            />
                        </IconWrapper>
                    }
                >
                    <span>{currentOrganization ? currentOrganization.name : 'Select organization'}</span>
                </LemonButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent loop align="start">
                <DropdownMenuLabel>Organizations</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <div className="flex flex-col gap-px">
                    {currentOrganization && (
                        <DropdownMenuItem asChild>
                            <LemonButton
                                icon={
                                    <UploadedLogo
                                        name={currentOrganization.name}
                                        entityId={currentOrganization.id}
                                        mediaId={currentOrganization.logo_media_id}
                                    />
                                }
                                title={`Switch to organization ${currentOrganization.name}`}
                                active
                                fullWidth
                                size="small"
                            >
                                <span>{currentOrganization.name}</span>
                                <AccessLevelIndicator organization={currentOrganization} />
                            </LemonButton>
                        </DropdownMenuItem>
                    )}
                    {otherOrganizations.map((otherOrganization) => (
                        <DropdownMenuItem key={otherOrganization.id} asChild>
                            <LemonButton
                                onClick={() => updateCurrentOrganization(otherOrganization.id)}
                                icon={
                                    <UploadedLogo
                                        name={otherOrganization.name}
                                        entityId={otherOrganization.id}
                                        mediaId={otherOrganization.logo_media_id}
                                    />
                                }
                                title={`Switch to organization ${otherOrganization.name}`}
                                fullWidth
                                size="small"
                            >
                                <span>{otherOrganization.name}</span>
                                <AccessLevelIndicator organization={otherOrganization} />
                            </LemonButton>
                        </DropdownMenuItem>
                    ))}
                    {preflight?.can_create_org && (
                        <DropdownMenuItem asChild>
                            <LemonButton
                                icon={
                                    <IconWrapper>
                                        <IconPlusSmall />
                                    </IconWrapper>
                                }
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
                                fullWidth
                                size="small"
                                data-attr="new-organization-button"
                            >
                                New organization
                            </LemonButton>
                        </DropdownMenuItem>
                    )}
                </div>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
