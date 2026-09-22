import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

// Single source of truth for "can the current user connect/reconnect integrations" on the frontend.
// Mirrors the backend IntegrationViewSet permission (TeamMemberStrictManagementPermission, which
// requires project-admin for writes). Returns a disabledReason string when the user lacks access,
// else null — wire it into the disabledReason of any connect/reconnect affordance so every
// integration gate stays in sync with the backend and with each other.
export function useIntegrationManagementRestriction(): string | null {
    return useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
}
