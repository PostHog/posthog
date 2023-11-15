import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'

export function OrganizationEmailPreferences(): JSX.Element {
    const { currentOrganization } = useValues(organizationLogic)
    const { updateOrganization } = useActions(organizationLogic)

    const isRestricted = !!useRestrictedArea({ minimumAccessLevel: OrganizationMembershipLevel.Admin })

    return (
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
    )
}
