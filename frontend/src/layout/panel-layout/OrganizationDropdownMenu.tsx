import { IconChevronRight, IconPlusSmall } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
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

import { panelLayoutLogic } from './panelLayoutLogic'

export function OrganizationDropdownMenu(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
    const { isLayoutNavCollapsed } = useValues(panelLayoutLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive className="max-w-[210px]" iconOnly={isLayoutNavCollapsed ? true : false}>
                    {currentOrganization ? (
                        <UploadedLogo
                            name={currentOrganization.name}
                            entityId={currentOrganization.id}
                            mediaId={currentOrganization.logo_media_id}
                            size={isLayoutNavCollapsed ? 'medium' : 'xsmall'}
                        />
                    ) : (
                        <UploadedLogo
                            name="?"
                            entityId=""
                            mediaId=""
                            size={isLayoutNavCollapsed ? 'medium' : 'xsmall'}
                        />
                    )}
                    {!isLayoutNavCollapsed && (
                        <>
                            <span className="truncate font-semibold">
                                {currentOrganization ? currentOrganization.name : 'Select organization'}
                            </span>
                            <IconChevronRight className="size-3 text-secondary rotate-90 group-data-[state=open]/button-primitive:rotate-270 transition-transform duration-200 prefers-reduced-motion:transition-none" />
                        </>
                    )}
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                loop
                align="start"
                className={`
                min-w-[200px] 
                max-w-[var(--project-panel-inner-width)] 
            `}
            >
                <DropdownMenuLabel>Organizations</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {currentOrganization && (
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            active
                            tooltip={`Current organization: ${currentOrganization.name}`}
                            tooltipPlacement="right"
                        >
                            <UploadedLogo
                                size="xsmall"
                                name={currentOrganization.name}
                                entityId={currentOrganization.id}
                                mediaId={currentOrganization.logo_media_id}
                            />
                            <span className="truncate">{currentOrganization.name}</span>
                            <div className="ml-auto">
                                <AccessLevelIndicator organization={currentOrganization} />
                            </div>
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                )}
                {otherOrganizations.map((otherOrganization) => (
                    <DropdownMenuItem key={otherOrganization.id} asChild>
                        <ButtonPrimitive
                            menuItem
                            onClick={() => updateCurrentOrganization(otherOrganization.id)}
                            tooltip={`Switch to organization: ${otherOrganization.name}`}
                            tooltipPlacement="right"
                        >
                            <UploadedLogo
                                size="xsmall"
                                name={otherOrganization.name}
                                entityId={otherOrganization.id}
                                mediaId={otherOrganization.logo_media_id}
                            />
                            {otherOrganization.name}
                            <div className="ml-auto">
                                <AccessLevelIndicator organization={otherOrganization} />
                            </div>
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                ))}
                {preflight?.can_create_org && (
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
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
                            tooltip="Create a new organization"
                            tooltipPlacement="right"
                        >
                            <IconPlusSmall className="size-4" />
                            New organization
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
