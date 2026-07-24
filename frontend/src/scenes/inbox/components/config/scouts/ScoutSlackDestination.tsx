import { useMountedLogic, useValues } from 'kea'

import { LemonSelect, Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { urls } from 'scenes/urls'

import type {
    SignalScoutOutputDestinationsApi,
    SignalScoutSlackDestinationApi,
} from 'products/signals/frontend/generated/api.schemas'

interface ScoutSlackDestinationProps {
    destination?: SignalScoutSlackDestinationApi | null
    disabledReason?: string
    onChange: (outputDestinations: SignalScoutOutputDestinationsApi) => void
}

export function ScoutSlackDestination({
    destination,
    disabledReason,
    onChange,
}: ScoutSlackDestinationProps): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const integrations = slackIntegrations ?? []
    const configuredIntegration = destination
        ? integrations.find((integration) => integration.id === destination.integration_id)
        : undefined
    const selectedIntegration = configuredIntegration ?? (integrations.length === 1 ? integrations[0] : null)

    const selectWorkspace = (integrationId: number): void => {
        onChange({ slack: { integration_id: integrationId, channel: null } })
    }

    const selectChannel = (channel: string | null): void => {
        if (!channel || !selectedIntegration) {
            onChange({})
            return
        }
        onChange({
            slack: { integration_id: selectedIntegration.id, channel },
        })
    }

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">Slack destination</span>
                <span className="text-[11.5px] text-muted">Post each scout run's output to a channel</span>
            </div>
            {integrationsLoading && slackIntegrations === undefined ? (
                <span className="text-xs text-muted">Loading Slack workspaces…</span>
            ) : integrations.length === 0 ? (
                <Link to={urls.settings('environment-integrations', 'integration-slack')}>
                    Connect a Slack workspace
                </Link>
            ) : (
                <div className="flex flex-col gap-2 max-w-md">
                    {integrations.length > 1 ? (
                        <LemonSelect
                            size="small"
                            value={selectedIntegration?.id ?? null}
                            options={integrations.map((integration) => ({
                                value: integration.id,
                                label: integration.display_name || `Slack workspace ${integration.id}`,
                            }))}
                            onChange={(integrationId) => integrationId != null && selectWorkspace(integrationId)}
                            placeholder="Select workspace"
                            disabledReason={disabledReason}
                        />
                    ) : null}
                    {selectedIntegration ? (
                        <SlackChannelPicker
                            integration={selectedIntegration}
                            value={configuredIntegration ? (destination?.channel ?? undefined) : undefined}
                            onChange={selectChannel}
                            disabled={disabledReason !== undefined}
                        />
                    ) : null}
                    <span className="text-[11.5px] text-muted">
                        PostHog must be in the channel. Invite it with <code>/invite @PostHog</code>.
                    </span>
                </div>
            )}
        </div>
    )
}
