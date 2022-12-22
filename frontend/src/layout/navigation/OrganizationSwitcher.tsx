import { useActions, useValues } from 'kea'
import { IconPlus } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { Lettermark } from 'lib/components/Lettermark/Lettermark'
import { membershipLevelToName } from 'lib/utils/permissioning'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { sceneLogic } from 'scenes/sceneLogic'
import { userLogic } from 'scenes/userLogic'
import { AvailableFeature, OrganizationBasicType } from '~/types'
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
    onClick,
}: {
    organization: OrganizationBasicType
    index: number
    onClick?: () => void
}): JSX.Element {
    const { updateCurrentOrganization } = useActions(userLogic)

    return (
        <LemonButton
            onClick={() => {
                updateCurrentOrganization(organization.id)
                onClick?.()
            }}
            icon={<Lettermark index={index} name={organization.name} />}
            status="stealth"
            title={`Switch to organization ${organization.name}`}
            fullWidth
        >
            {organization.name}
            <AccessLevelIndicator organization={organization} />
        </LemonButton>
    )
}

export function NewOrganizationButton({ onClick }: { onClick?: () => void }): JSX.Element {
    const { closeSitePopover, showCreateOrganizationModal } = useActions(navigationLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() => {
                onClick?.()
                guardAvailableFeature(
                    AvailableFeature.ORGANIZATIONS_PROJECTS,
                    'multiple organizations',
                    'Organizations group people building products together. An organization can then have multiple projects.',
                    () => {
                        closeSitePopover()
                        showCreateOrganizationModal()
                    },
                    {
                        cloud: false,
                        selfHosted: true,
                    }
                )
            }}
            fullWidth
        >
            New organization
        </LemonButton>
    )
}

export function OrganizationSwitcherOverlay({ onClose }: { onClose: () => void }): JSX.Element {
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
                    status="stealth"
                    title={`Switch to organization ${currentOrganization.name}`}
                    fullWidth
                >
                    <strong>{currentOrganization.name}</strong>
                    <AccessLevelIndicator organization={currentOrganization} />
                </LemonButton>
            )}
            {otherOrganizations.map((otherOrganization, i) => (
                <OtherOrganizationButton
                    key={otherOrganization.id}
                    organization={otherOrganization}
                    index={i}
                    onClick={onClose}
                />
            ))}
            {preflight?.can_create_org && <NewOrganizationButton onClick={onClose} />}
        </div>
    )
}
