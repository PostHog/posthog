import { useActions, useValues } from 'kea'
import { IconPlus } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { LemonRow } from 'lib/components/LemonRow'
import { LemonDivider } from 'lib/components/LemonDivider'
import { LemonTag } from 'lib/components/LemonTag/LemonTag'
import { Lettermark } from 'lib/components/Lettermark/Lettermark'
import { membershipLevelToName } from 'lib/utils/permissioning'
import React from 'react'
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

export function OtherOrganizationButton({ organization }: { organization: OrganizationBasicType }): JSX.Element {
    const { updateCurrentOrganization } = useActions(userLogic)

    return (
        <LemonButton
            onClick={() => updateCurrentOrganization(organization.id)}
            icon={<Lettermark name={organization.name} />}
            className="SitePopover__organization"
            status="stealth"
            title={`Switch to organization ${organization.name}`}
            fullWidth
        >
            {organization.name}
            <AccessLevelIndicator organization={organization} />
        </LemonButton>
    )
}

export function NewOrganizationButton(): JSX.Element {
    const { closeSitePopover, showCreateOrganizationModal } = useActions(navigationLogic)
    const { guardAvailableFeature } = useActions(sceneLogic)

    return (
        <LemonButton
            icon={<IconPlus />}
            onClick={() =>
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
                <LemonRow status="highlighted" fullWidth icon={<Lettermark name={currentOrganization.name} />}>
                    <div className="SitePopover__main-info SitePopover__organization">
                        <strong>{currentOrganization.name}</strong>
                        <AccessLevelIndicator organization={currentOrganization} />
                    </div>
                </LemonRow>
            )}
            {otherOrganizations.map((otherOrganization) => (
                <OtherOrganizationButton key={otherOrganization.id} organization={otherOrganization} />
            ))}
            {preflight?.can_create_org && <NewOrganizationButton />}
        </div>
    )
}
