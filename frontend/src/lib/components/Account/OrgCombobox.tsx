import { useActions, useValues } from 'kea'

import { IconCheck, IconPlusSmall } from '@posthog/icons'

import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo'
import { IconBlank } from 'lib/lemon-ui/icons'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { Combobox } from 'lib/ui/Combobox/Combobox'
import { Label } from 'lib/ui/Label/Label'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { globalModalsLogic } from '~/layout/GlobalModals'
import { AccessLevelIndicator } from '~/layout/navigation/AccessLevelIndicator'
import { AvailableFeature } from '~/types'

import { upgradeModalLogic } from '../UpgradeModal/upgradeModalLogic'

export function OrgCombobox({ allowCreate = true }: { allowCreate?: boolean }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
    const { currentOrganization } = useValues(organizationLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { updateCurrentOrganization } = useActions(userLogic)
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    return (
        <Combobox>
            <Combobox.Search placeholder="Filter organizations..." />
            <Combobox.Content>
                <Label intent="menu" className="px-2">
                    Current organization
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

                <Label intent="menu" className="px-2 mt-2">
                    Other organizations
                </Label>
                <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />

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

                {preflight?.can_create_org && allowCreate && (
                    <>
                        <div className="-mx-1 my-1 h-px bg-border-primary shrink-0" />
                        <Combobox.Item asChild>
                            <ButtonPrimitive
                                menuItem
                                data-attr="new-organization-button"
                                onClick={() =>
                                    guardAvailableFeature(
                                        AvailableFeature.ORGANIZATIONS_PROJECTS,
                                        () => {
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
                    </>
                )}
            </Combobox.Content>
        </Combobox>
    )
}
