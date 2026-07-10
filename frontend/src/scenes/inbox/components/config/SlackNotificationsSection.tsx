import { useActions, useMountedLogic, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonSelect, LemonSkeleton, LemonSwitch, Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { IconSlack } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { SignalReportPriority } from '../../types'

const NOTIFY_ALL_VALUE = '__all__'

/** Minimum report priority that triggers a Slack ping. "All priorities" maps to a null min-priority. */
const MIN_PRIORITY_OPTIONS: { value: SignalReportPriority | typeof NOTIFY_ALL_VALUE; label: string }[] = [
    { value: NOTIFY_ALL_VALUE, label: 'All priorities' },
    { value: 'P0', label: 'P0 only' },
    { value: 'P1', label: 'P1 and above' },
    { value: 'P2', label: 'P2 and above' },
    { value: 'P3', label: 'P3 and above' },
    { value: 'P4', label: 'P4 and above' },
]

/** Shown when there's no Slack workspace connected – links out to integration settings. */
function ConnectSlackPrompt(): JSX.Element {
    return (
        <Link
            to={urls.settings('environment-integrations', 'integration-slack')}
            className="group flex items-center justify-between gap-3 rounded border bg-bg-light px-3 py-2.5 no-underline transition-colors hover:border-primary-3000 hover:bg-bg-3000"
        >
            <div className="flex items-start gap-3 min-w-0">
                <IconSlack className="size-5 shrink-0 mt-0.5 grayscale" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">Connect a Slack workspace</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        Connect Slack to post reports to a team channel and get pinged when you're a suggested reviewer.
                    </p>
                </div>
            </div>
            <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
        </Link>
    )
}

/**
 * Team-wide channel where every actionable report is posted regardless of the suggested reviewer,
 * backed by `default_slack_notification_channel` on `signalTeamConfigLogic`. Clearing the channel
 * disables the team default. The backend routes the team channel through the team's first Slack
 * integration (`_get_team_slack_integration`), so we target `integrations[0]` here too.
 */
function TeamChannelCard({ integration }: { integration: IntegrationType }): JSX.Element {
    const { teamConfig } = useValues(signalTeamConfigLogic)
    const { setDefaultSlackNotificationChannel } = useActions(signalTeamConfigLogic)
    const channel = teamConfig?.default_slack_notification_channel ?? null

    return (
        <div className="flex flex-col gap-3 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start gap-3 min-w-0">
                <IconSlack className="size-5 shrink-0 mt-0.5 grayscale" />
                <div className="min-w-0">
                    <div className="font-medium text-sm text-default">Notify the whole team</div>
                    <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                        Post every report to one channel, whether or not a reviewer is suggested. PostHog must be in the
                        channel – invite it with <code>/invite @PostHog</code>. Clear the channel to turn this off.
                    </p>
                </div>
            </div>

            <div className="flex flex-col gap-1 min-w-0 max-w-md border-t border-primary border-dashed pt-3">
                <span className="text-xs text-secondary">Channel</span>
                <SlackChannelPicker
                    integration={integration}
                    value={channel ?? undefined}
                    onChange={(next) => setDefaultSlackNotificationChannel(next)}
                />
            </div>
        </div>
    )
}

/**
 * Per-user Slack notification controls – a cloud port of desktop's
 * `SlackInboxNotificationsSettings` / `SignalSlackNotificationsSettings`.
 * Notifications are enabled when an integration + channel are both set; the
 * enable toggle clears them to disable. Min-priority gates which reports ping.
 * Backed by the `slack_notification_*` fields on `userAutonomyLogic`.
 */
function PerUserChannelCard({ integrations }: { integrations: IntegrationType[] }): JSX.Element {
    const { autonomyConfig, autonomyConfigLoading, slackPickersExpanded } = useValues(userAutonomyLogic)
    const { updateSlackNotifications, setSlackPickersExpanded } = useActions(userAutonomyLogic)

    // Workspace is shared with the team default. Default to the only workspace, or the user's saved pick.
    const selectedIntegrationId = autonomyConfig?.slack_notification_integration_id ?? null
    const effectiveIntegration =
        integrations.find((i) => i.id === selectedIntegrationId) ?? (integrations.length === 1 ? integrations[0] : null)
    const channel = autonomyConfig?.slack_notification_channel ?? null
    const minPriority = autonomyConfig?.slack_notification_min_priority ?? null
    const notificationsEnabled = !!effectiveIntegration && !!channel

    const onToggleEnabled = (enabled: boolean): void => {
        if (enabled) {
            // Turning on just opens the workspace/channel pickers – the actual enable
            // happens once a channel is chosen. Reveal them even when the workspace is
            // ambiguous (multiple connected) so the user can pick one; persist it now
            // only when it's unambiguous.
            setSlackPickersExpanded(true)
            if (effectiveIntegration && selectedIntegrationId === null) {
                updateSlackNotifications({ integrationId: effectiveIntegration.id })
            }
        } else {
            // Disable by clearing the target and collapsing the pickers.
            setSlackPickersExpanded(false)
            updateSlackNotifications({ integrationId: null, channel: null })
        }
    }

    const onWorkspaceChange = (integrationId: number): void => {
        // Switching workspaces clears the channel – it won't exist in the new workspace.
        updateSlackNotifications({ integrationId, channel: null })
    }

    const onChannelChange = (next: string | null): void => {
        if (next === null) {
            updateSlackNotifications({ channel: null })
            return
        }
        if (!effectiveIntegration) {
            return
        }
        updateSlackNotifications({ integrationId: effectiveIntegration.id, channel: next })
    }

    const onMinPriorityChange = (value: string): void => {
        updateSlackNotifications({
            minPriority: value === NOTIFY_ALL_VALUE ? null : (value as SignalReportPriority),
        })
    }

    // "On" means the pickers are visible: the user expanded them, or a saved integration/channel
    // already implies an enabled state.
    const showPickers = slackPickersExpanded || selectedIntegrationId !== null || !!channel

    return (
        <div className="flex flex-col gap-3 rounded border bg-bg-light px-3 py-2.5">
            <div className="flex items-start justify-between gap-4">
                <div className="flex items-start gap-3 min-w-0">
                    <IconSlack className="size-5 shrink-0 mt-0.5 grayscale" />
                    <div className="min-w-0">
                        <div className="font-medium text-sm text-default">Notify me directly</div>
                        <p className="text-xs text-secondary mt-0.5 mb-0 max-w-xl">
                            When you're a suggested reviewer, get pinged in your own channel. PostHog must be in the
                            channel – invite it with <code>/invite @PostHog</code>.
                        </p>
                    </div>
                </div>
                <LemonSwitch
                    checked={showPickers}
                    onChange={onToggleEnabled}
                    disabled={autonomyConfigLoading && autonomyConfig === null}
                    aria-label="Enable Slack notifications"
                />
            </div>

            {showPickers && (
                <div className="flex flex-col gap-3 border-t border-primary border-dashed pt-3">
                    {integrations.length > 1 && (
                        <div className="flex flex-col gap-1 min-w-0">
                            <span className="text-xs text-secondary">Workspace</span>
                            <LemonSelect
                                className="max-w-[260px]"
                                value={effectiveIntegration?.id ?? null}
                                options={integrations.map((i) => ({
                                    value: i.id,
                                    label: i.display_name || `Slack workspace ${i.id}`,
                                }))}
                                onChange={(next) => next != null && onWorkspaceChange(next)}
                                placeholder="Select workspace"
                            />
                        </div>
                    )}

                    {effectiveIntegration && (
                        <div className="flex flex-col gap-1 min-w-0 max-w-md">
                            <span className="text-xs text-secondary">Channel</span>
                            <SlackChannelPicker
                                integration={effectiveIntegration}
                                value={channel ?? undefined}
                                onChange={onChannelChange}
                            />
                        </div>
                    )}

                    <div className="flex flex-col gap-1 min-w-0">
                        <span className="text-xs text-secondary">Min. priority</span>
                        <LemonSelect
                            className="max-w-[240px]"
                            value={minPriority ?? NOTIFY_ALL_VALUE}
                            options={MIN_PRIORITY_OPTIONS}
                            disabledReason={!notificationsEnabled ? 'Pick a channel first' : undefined}
                            onChange={onMinPriorityChange}
                        />
                    </div>
                </div>
            )}
        </div>
    )
}

/** Slack inbox notification settings: a team-wide channel plus per-user reviewer pings. */
export function SlackNotificationsSection(): JSX.Element {
    useMountedLogic(integrationsLogic)
    useMountedLogic(userAutonomyLogic)
    useMountedLogic(signalTeamConfigLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    if (integrationsLoading && slackIntegrations === undefined) {
        return <LemonSkeleton className="h-20 w-full" />
    }

    const integrations = slackIntegrations ?? []
    if (integrations.length === 0) {
        return <ConnectSlackPrompt />
    }

    return (
        <div className="flex flex-col gap-3">
            <TeamChannelCard integration={integrations[0]} />
            <PerUserChannelCard integrations={integrations} />
        </div>
    )
}
