import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/** Why the user can't change marketing analytics setup, or null when they can. The backend
 * requires both project admin and editor access to marketing analytics for these writes. */
export function useMarketingAnalyticsEditDisabledReason(): string | null {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    return (
        restrictedReason ??
        getAccessControlDisabledReason(AccessControlResourceType.MarketingAnalytics, AccessControlLevel.Editor)
    )
}
