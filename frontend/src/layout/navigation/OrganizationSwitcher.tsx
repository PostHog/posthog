import { IconPlus } from '@posthog/icons'
import { useActions, useValues } from 'kea'
import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTag } from 'lib/lemon-ui/LemonTag/LemonTag'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
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
}: {
    organization: OrganizationBasicType
    index: number
}): JSX.Element {
    const { updateCurrentOrganization } = useActions(userLogic)

    return (
        <LemonButton
            onClick={() => updateCurrentOrganization(organization.id)}
            icon={
                <UploadedLogo
                    name={organization.name}
                    entityId={organization.id}
                    mediaId={organization.logo_media_id}
                />
            }
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
    const { guardAvailableFeature } = useValues(upgradeModalLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
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
            data-attr="new-organization-button"
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
                >
                    {currentOrganization.name}
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
