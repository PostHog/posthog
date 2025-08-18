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

    const allowPubliclySharedResourcesRestrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    if (!user) {
        return null
    }

    return (
        <>
            <PayGateMini feature={AvailableFeature.ORGANIZATION_SECURITY_SETTINGS}>
                <h3 className="mt-4">Public sharing</h3>

                <p>Control external access to shared dashboards, insights, and recordings.</p>

                <LemonSwitch
                    label={
                        <span>
                            Allow publicly shared resources{' '}
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
                    disabledReason={allowPubliclySharedResourcesRestrictionReason}
                />
            </PayGateMini>
        </>
    )
}
