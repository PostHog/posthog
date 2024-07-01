import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrgAdminConfiguration(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const isRestricted = !!useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
        <div className="space-y-2">
            <LemonSwitch
                data-attr="is-member-join-email-enabled-switch"
                onChange={(checked) => {
                    updateOrganization({ is_member_join_email_enabled: checked })
                }}
                checked={!!currentOrganization?.is_member_join_email_enabled}
                disabled={isRestricted || !currentOrganization}
                label="Email all current members when a new member joins"
                bordered
            />

            <LemonSwitch
                data-attr="billing-access-level"
                onChange={(checked) => {
                    updateOrganization({
                        billing_access_level: checked
                            ? OrganizationMembershipLevel.Admin
                            : OrganizationMembershipLevel.Member,
                    })
                }}
                checked={currentOrganization?.billing_access_level === OrganizationMembershipLevel.Admin}
                disabled={isRestricted || !currentOrganization}
                label="Restrict access to billing information to admins only"
                bordered
            />
        </div>
    )
}
