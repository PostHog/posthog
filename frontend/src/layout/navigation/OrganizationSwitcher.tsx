import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'

import { upgradeModalLogic } from 'lib/components/UpgradeModal/upgradeModalLogic'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { UploadedLogo } from 'lib/lemon-ui/UploadedLogo/UploadedLogo'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, OrganizationBasicType } from '~/types'

import { globalModalsLogic } from '../GlobalModals'
import { AccessLevelIndicator } from './AccessLevelIndicator'
import { navigationLogic } from './navigationLogic'

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
            icon={<IconPlusSmall />}
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

// OrganizationSwitcherOverlay has been replaced with the OrganizationDropdownMenu,
// the above code is still in use for the AccountPopover, for now.
