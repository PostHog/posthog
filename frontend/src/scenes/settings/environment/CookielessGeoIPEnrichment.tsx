import { useActions, useValues } from 'kea'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { teamLogic } from 'scenes/teamLogic'

export function CookielessGeoIPEnrichmentSetting(): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    return (
        <LemonSwitch
            data-attr="cookieless-geoip-enrichment-enabled"
            onChange={(checked) => {
                updateCurrentTeam({ cookieless_geoip_enrichment_enabled: checked })
            }}
            checked={!!currentTeam?.cookieless_geoip_enrichment_enabled}
            disabledReason={restrictedReason ?? undefined}
            bordered
            label="Enable GeoIP enrichment for cookieless events"
        />
    )
}
