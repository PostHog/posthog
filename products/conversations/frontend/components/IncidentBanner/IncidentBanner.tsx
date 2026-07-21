import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { incidentBannerLogic } from './incidentBannerLogic'

export function IncidentBanner(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)

    // Gate before mounting the inner component so ineligible teams never fire
    // the incidents request (mounting the logic loads immediately).
    const trendsEnabled = currentTeam?.conversations_settings?.trends_enabled ?? true
    if (!featureFlags[FEATURE_FLAGS.PRODUCT_SUPPORT_TICKET_TRENDS] || !trendsEnabled) {
        return null
    }
    return <IncidentBannerInner />
}

function IncidentBannerInner(): JSX.Element | null {
    const { activeIncidents } = useValues(incidentBannerLogic)
    const { dismissIncident } = useActions(incidentBannerLogic)

    if (activeIncidents.length === 0) {
        return null
    }

    const first = activeIncidents[0]
    const title = first.details?.title ?? `${first.observed_count} tickets in an unusually short window`
    const suffix = activeIncidents.length > 1 ? ` (+${activeIncidents.length - 1} more)` : ''

    return (
        <LemonBanner
            type="warning"
            action={{ children: 'View trends', to: urls.supportTrends() }}
            onClose={() => dismissIncident(first.id)}
        >
            Possible incident: {title}
            {suffix}
        </LemonBanner>
    )
}
