import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { IntegrationKind, IntegrationType } from '~/types'

// Integrations still authenticated through a retiring OAuth app, with the date it stops working.
// The backend flags the affected connections on refresh (`oauth_uses_legacy_client`); reconnecting
// moves them to the current app and clears the flag.
const RETIRING_OAUTH_APPS: Partial<Record<IntegrationKind, { name: string; retiresOn: string }>> = {
    'bing-ads': { name: 'Bing Ads', retiresOn: '2026-08-07' },
}

const usesRetiringApp = (integration: IntegrationType): boolean =>
    !!RETIRING_OAUTH_APPS[integration.kind] && !!integration.config?.oauth_uses_legacy_client

export const LegacyOAuthReconnectBanner = (): JSX.Element | null => {
    const { integrations } = useValues(integrationsLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const affected = (integrations ?? []).find(usesRetiringApp)

    if (!affected || !featureFlags[FEATURE_FLAGS.LEGACY_OAUTH_RECONNECT_WARNING]) {
        return null
    }

    const app = RETIRING_OAUTH_APPS[affected.kind]!

    return (
        <LemonBanner
            type="warning"
            className="mb-2 mt-4"
            action={{
                children: 'Reconnect',
                disableClientSideRouting: true,
                to: api.integrations.authorizeUrl({ kind: affected.kind, next: window.location.pathname }),
                disabledReason: restrictedReason,
            }}
        >
            Your {app.name} connection stops working on {dayjs(app.retiresOn).format('MMMM D, YYYY')}. Reconnect it to
            keep your marketing data syncing. Nothing else about your setup changes.
        </LemonBanner>
    )
}
