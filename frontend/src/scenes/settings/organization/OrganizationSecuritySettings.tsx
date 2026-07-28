import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { PayGateMini } from 'lib/components/PayGateMini/PayGateMini'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

export function OrganizationSecuritySettings(): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)
    const { user } = useValues(userLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const adminRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    if (!user) {
        return null
    }

    return (
        <>
            <PayGateMini feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}>
                <LemonSwitch
                    label={
                        <span>
                            Enable publicly shared resources{' '}
                            <Tooltip title="When disabled, sharing links and public dashboards will be blocked for this organization.">
                                <IconInfo className="mr-1" />
                            </Tooltip>
                        </span>
                    }
                    bordered
                    data-attr="org-allow-publicly-shared-resources-toggle"
                    checked={!!currentOrganization?.allow_publicly_shared_resources}
                    onChange={(allow_publicly_shared_resources) => {
                        if (!allow_publicly_shared_resources) {
                            LemonDialog.open({
                                title: 'Disable public sharing?',
                                description: (
                                    <div>
                                        <p>
                                            Disabling public sharing will immediately break all existing sharing links
                                            and public dashboards for this organization.
                                        </p>
                                        <p>
                                            Users will no longer be able to access any shared resources until this
                                            setting is re-enabled.
                                        </p>
                                    </div>
                                ),
                                primaryButton: {
                                    children: 'Disable sharing',
                                    status: 'danger',
                                    onClick: () => updateOrganization({ allow_publicly_shared_resources }),
                                },
                                secondaryButton: {
                                    children: 'Cancel',
                                },
                            })
                        } else {
                            updateOrganization({ allow_publicly_shared_resources })
                        }
                    }}
                    disabledReason={adminRestrictionReason}
                />
                <LemonSwitch
                    label={
                        <span>
                            Members can see the full member list{' '}
                            <Tooltip title="When disabled, only admins and owners can see all organization members. Members will only see themselves in the members list, and only people with project access in a project's access control.">
                                <IconInfo className="mr-1" />
                            </Tooltip>
                        </span>
                    }
                    bordered
                    className="mt-2"
                    data-attr="org-members-can-see-org-members-toggle"
                    checked={currentOrganization?.members_can_see_org_members ?? true}
                    onChange={(members_can_see_org_members) => {
                        updateOrganization({ members_can_see_org_members })
                    }}
                    disabledReason={adminRestrictionReason}
                />
            </PayGateMini>
        </>
    )
}
