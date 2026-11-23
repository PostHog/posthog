import { Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { OrganizationMembershipLevel } from 'lib/constants'

import { WarehouseLoginsPanel } from './WarehouseLoginsPanel'

/** Trino login management for organization admins. Members get a note, and the logins logic never mounts for them. */
export function WarehouseLoginsSection(): JSX.Element {
    const adminRestrictionReason = useRestrictedArea({
        scope: RestrictionScope.Organization,
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
    })

    if (adminRestrictionReason) {
        return <Text variant="muted">Only organization admins can manage warehouse logins.</Text>
    }
    return <WarehouseLoginsPanel />
}
