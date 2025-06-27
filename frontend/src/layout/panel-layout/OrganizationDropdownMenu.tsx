import { IconCheck, IconChevronRight, IconPlusSmall } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { IconBlank } from 'lib/lemon-ui/icons'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Combobox } from 'lib/ui/Combobox/Combobox'
import { Label } from 'lib/ui/Label/Label'
import {
    PopoverPrimitive,
    PopoverPrimitiveContent,
    PopoverPrimitiveTrigger,
} from 'lib/ui/PopoverPrimitive/PopoverPrimitive'
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
        <>
            <PopoverPrimitive>
                <PopoverPrimitiveTrigger asChild>
                    <ButtonPrimitive
                        className="max-w-[210px]"
                        iconOnly={isLayoutNavCollapsed ? true : false}
                        data-attr="tree-navbar-organization-dropdown-button"
                        size="sm"
                    >
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
                </PopoverPrimitiveTrigger>
                <PopoverPrimitiveContent
                    align="start"
                    className="w-[var(--project-panel-inner-width)] max-w-[var(--project-panel-inner-width)]"
                >
                    <Combobox>
                        <Combobox.Search placeholder="Filter organizations..." />
                        <Combobox.Content className="max-h-[calc(90vh-100px)]">
                            <Label intent="menu" className="px-2">
                                Organizations
                            </Label>
                            <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />

                            <Combobox.Empty>No organizations found</Combobox.Empty>

                            {currentOrganization && (
                                <Combobox.Group value={[currentOrganization.name]}>
                                    <Combobox.Item asChild>
                                        <ButtonPrimitive
                                            menuItem
                                            active
                                            tooltip={`Current organization: ${currentOrganization.name}`}
                                            tooltipPlacement="right"
                                            data-attr="tree-navbar-organization-dropdown-current-organization-button"
                                        >
                                            <IconCheck className="text-tertiary" />
                                            <UploadedLogo
                                                size="xsmall"
                                                name={currentOrganization.name}
                                                entityId={currentOrganization.id}
                                                mediaId={currentOrganization.logo_media_id}
                                            />
                                            <span className="truncate max-w-full">{currentOrganization.name}</span>
                                            <div className="ml-auto">
                                                <AccessLevelIndicator organization={currentOrganization} />
                                            </div>
                                        </ButtonPrimitive>
                                    </Combobox.Item>
                                </Combobox.Group>
                            )}

                            {otherOrganizations.map((otherOrganization) => (
                                <Combobox.Group value={[otherOrganization.name]} key={otherOrganization.id}>
                                    <Combobox.Item key={otherOrganization.id} asChild>
                                        <ButtonPrimitive
                                            menuItem
                                            onClick={() => updateCurrentOrganization(otherOrganization.id)}
                                            tooltip={`Switch to organization: ${otherOrganization.name}`}
                                            tooltipPlacement="right"
                                            data-attr="tree-navbar-organization-dropdown-other-organization-button"
                                        >
                                            <IconBlank />
                                            <UploadedLogo
                                                size="xsmall"
                                                name={otherOrganization.name}
                                                entityId={otherOrganization.id}
                                                mediaId={otherOrganization.logo_media_id}
                                            />
                                            <span className="truncate max-w-full">{otherOrganization.name}</span>
                                            <div className="ml-auto">
                                                <AccessLevelIndicator organization={otherOrganization} />
                                            </div>
                                        </ButtonPrimitive>
                                    </Combobox.Item>
                                </Combobox.Group>
                            ))}

                            {preflight?.can_create_org && (
                                <Combobox.Item asChild>
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
                                </Combobox.Item>
                            )}
                        </Combobox.Content>
                    </Combobox>
                </PopoverPrimitiveContent>
            </PopoverPrimitive>
        </>
    )
}
