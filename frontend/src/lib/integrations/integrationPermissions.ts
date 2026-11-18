import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'

// Single source of truth for "can the current user overwrite an existing integration" on the frontend.
// The backend lets any project member create an integration, but IntegrationSerializer.create requires
// project admin to overwrite one (the creator of a Google Calendar connection is the only exception).
// Returns a disabledReason string when the user lacks access, else null. Wire it into the
// disabledReason of any affordance that can overwrite an integration, such as a reconnect or an OAuth
// connect that can land on an account that is already connected, so these gates stay in sync.
export function useIntegrationManagementRestriction(): string | null {
    return useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
}
