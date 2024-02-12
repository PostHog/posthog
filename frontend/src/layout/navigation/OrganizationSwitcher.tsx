import { useActions, useValues } from 'kea'
import { IconPlus } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { Lettermark } from 'lib/lemon-ui/Lettermark'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, OrganizationBasicType } from '~/types'

import { globalModalsLogic } from '../GlobalModals'
import { navigationLogic } from './navigationLogic'

export function AccessLevelIndicator({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    return (
        <LemonTag className="AccessLevelIndicator" title={`Your ${organization.name} organization access level`}>
            {(organization.membership_level ? membershipLevelToName.get(organization.membership_level) : null) || '?'}
        </LemonTag>
    )
}

export function OtherOrganizationButton({
    organization,
    index,
}: {
    organization: OrganizationBasicType
    index: number
}): JSX.Element {
    const { updateCurrentOrganization } = useActions(userLogic)

    return (
        <LemonButton
            onClick={() => updateCurrentOrganization(organization.id)}
            icon={<Lettermark index={index} name={organization.name} />}
            title={`Switch to organization ${organization.name}`}
            fullWidth
        >
            {organization.name}
            <AccessLevelIndicator organization={organization} />
        </LemonButton>
    )
}

export function NewOrganizationButton(): JSX.Element {
    const { closeAccountPopover } = useActions(navigationLogic)
    const { showCreateOrganizationModal } = useActions(globalModalsLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() =>
                guardAvailableFeature(
                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                    'multiple organizations',
                    'Organizations group people building products together. An organization can have multiple projects.',
                    () => {
                        closeAccountPopover()
                        showCreateOrganizationModal()
                    },
                    {
                        cloud: false,
                        selfHosted: true,
                    }
                )
            }
            fullWidth
        >
            New organization
        </LemonButton>
    )
}

export function OrganizationSwitcherOverlay(): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const { otherOrganizations } = useValues(userLogic)
    const { currentOrganization } = useValues(organizationLogic)
    return (
        <div>
            <h5>Organizations</h5>
            <LemonDivider />
            {currentOrganization && (
                <LemonButton
                    icon={<Lettermark name={currentOrganization.name} />}
                    title={`Switch to organization ${currentOrganization.name}`}
                    fullWidth
                >
                    <strong>{currentOrganization.name}</strong>
                    <AccessLevelIndicator organization={currentOrganization} />
                </LemonButton>
            )}
            {otherOrganizations.map((otherOrganization, i) => (
                <OtherOrganizationButton key={otherOrganization.id} organization={otherOrganization} index={i} />
            ))}
            {preflight?.can_create_org && <NewOrganizationButton />}
        </div>
    )
}
