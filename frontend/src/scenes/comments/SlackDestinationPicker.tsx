import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonLabel } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { Spinner } from 'lib/lemon-ui/Spinner'

export type SlackDestinationPickerProps = {
    integrationId: number | null
    /** The SlackChannelPicker's composite `CHANNEL_ID|#name` value. */
    channel: string | null
    onIntegrationChange: (integrationId: number | null) => void
    onChannelChange: (channel: string | null) => void
    /** Extra classes for the picker container; not applied to the loading/not-configured states. */
    className?: string
}

/** Slack workspace + channel picker shared by the comment composer and the send-to-Slack modal. */
export function SlackDestinationPicker({
    integrationId,
    channel,
    onIntegrationChange,
    onChannelChange,
    className,
}: SlackDestinationPickerProps): JSX.Element {
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const selectedIntegration = slackIntegrations?.find((integration) => integration.id === integrationId)

    // Integrations load async on mount — don't flash "not configured" at users who have Slack set up.
    if (!slackIntegrations?.length && integrationsLoading) {
        return (
            <div className="flex justify-center p-2">
                <Spinner />
            </div>
        )
    }

    if (!slackIntegrations?.length) {
        return <SlackNotConfiguredBanner />
    }

    return (
        <div className={clsx('flex flex-col gap-2', className)}>
            <div className="flex flex-col gap-1">
                <LemonLabel>Slack workspace</LemonLabel>
                <IntegrationChoice
                    integration="slack"
                    value={integrationId ?? undefined}
                    onChange={onIntegrationChange}
                />
            </div>
            {selectedIntegration ? (
                <div className="flex flex-col gap-1">
                    <LemonLabel>Channel</LemonLabel>
                    <SlackChannelPicker
                        value={channel ?? undefined}
                        onChange={onChannelChange}
                        integration={selectedIntegration}
                    />
                </div>
            ) : null}
        </div>
    )
}
