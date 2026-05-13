import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { IntegrationView } from 'lib/integrations/IntegrationView'

import IconDiscord from 'public/services/discord.png'

export function PostHogCodeDiscordIntegration(): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })
    const { posthogCodeDiscordIntegrations, posthogCodeDiscordAvailable } = useValues(integrationsLogic)
    const flagEnabled = useFeatureFlag('POSTHOG_CODE_DISCORD_AVAILABILITY')
    const canConnect = posthogCodeDiscordAvailable && flagEnabled

    return (
        <div>
            <p>Connect Discord to PostHog Code to kick off tasks like pull requests directly from Discord.</p>

            <div className="deprecated-space-y-2">
                {posthogCodeDiscordIntegrations?.map((integration) => (
                    <IntegrationView key={integration.id} integration={integration} />
                ))}

                <div>
                    {canConnect ? (
                        <LemonButton
                            type="primary"
                            disableClientSideRouting
                            to={api.integrations.authorizeUrl({ kind: 'discord-posthog-code' })}
                            disabledReason={restrictedReason}
                            icon={<img src={IconDiscord} alt="" height="20" width="20" />}
                        >
                            Add to Discord
                        </LemonButton>
                    ) : (
                        <p className="text-secondary">
                            The PostHog Code Discord integration is not configured for this instance.
                        </p>
                    )}
                </div>
            </div>
        </div>
    )
}
