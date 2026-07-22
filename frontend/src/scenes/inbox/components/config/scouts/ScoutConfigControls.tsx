import { useMountedLogic, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSelect, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker } from 'lib/integrations/SlackIntegrationHelpers'
import { urls } from 'scenes/urls'

import type { IntegrationType } from '~/types'

import { SignalScoutConfig, SignalScoutConfigUpdate } from '../../../types'
import { formatRunInterval, prettifyScoutSkillName, RUN_INTERVAL_OPTIONS } from '../../../utils/scoutRunsWindow'

interface ScoutConfigControlsProps {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}

interface ScoutConfigFormProps extends ScoutConfigControlsProps {
    onDelete?: (configId: string) => void
    /** True while this scout's delete request is in flight — disables the delete button. */
    deleting?: boolean
}

function intervalOptions(config: SignalScoutConfig): { value: string; label: string }[] {
    const options = RUN_INTERVAL_OPTIONS.map((option) => ({
        value: String(option.minutes),
        label: option.label,
    }))
    if (!RUN_INTERVAL_OPTIONS.some((option) => option.minutes === config.run_interval_minutes)) {
        options.push({
            value: String(config.run_interval_minutes),
            label: formatRunInterval(config.run_interval_minutes),
        })
    }
    return options
}

/** Enable/disable toggle for a scout. Lives on the row, not in the settings form. */
export function ScoutEnabledSwitch({ config, onUpdate, updating = false }: ScoutConfigControlsProps): JSX.Element {
    return (
        <Tooltip title={config.enabled ? 'Disable scout' : 'Enable scout'}>
            <span>
                <LemonSwitch
                    size="small"
                    checked={config.enabled}
                    onChange={(checked) => onUpdate(config.id, { enabled: checked })}
                    loading={updating}
                    disabledReason={updating ? 'Saving…' : undefined}
                    aria-label={`${config.skill_name} enabled`}
                />
            </span>
        </Tooltip>
    )
}

/**
 * Labeled settings form for one scout, shown when a fleet row's gear is toggled
 * open. Everything except enablement, which stays on the row.
 */
export function ScoutConfigForm({
    config,
    onUpdate,
    onDelete,
    deleting,
    updating = false,
}: ScoutConfigFormProps): JSX.Element {
    useMountedLogic(integrationsLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Cadence</span>
                    <span className="text-[11.5px] text-muted">How often the scout is dispatched</span>
                </div>
                <LemonSelect
                    size="small"
                    value={String(config.run_interval_minutes)}
                    options={intervalOptions(config)}
                    disabledReason={updating ? 'Saving…' : config.enabled ? undefined : 'Enable the scout first'}
                    className="w-36"
                    onChange={(value) => onUpdate(config.id, { run_interval_minutes: Number(value) })}
                />
            </div>
            <ScoutSlackDestination
                config={config}
                onUpdate={onUpdate}
                integrations={slackIntegrations ?? []}
                loading={integrationsLoading && slackIntegrations === undefined}
                updating={updating}
            />
            {/* Only custom scouts are deletable. A canonical scout would be re-seeded from disk after
                deletion (and couldn't be re-added from the UI), so its terminal action stays disable. */}
            {onDelete && config.scout_origin === 'custom' ? (
                <div className="flex items-center justify-between gap-4 border-t border-primary pt-2">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Delete scout</span>
                        <span className="text-[11.5px] text-muted">Permanently deletes the scout and its skill</span>
                    </div>
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        loading={deleting}
                        disabledReason={deleting ? 'Deleting…' : undefined}
                        onClick={() => confirmDeleteScout(config, onDelete)}
                    >
                        Delete
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

function ScoutSlackDestination({
    config,
    onUpdate,
    integrations,
    loading,
    updating = false,
}: ScoutConfigControlsProps & { integrations: IntegrationType[]; loading: boolean }): JSX.Element {
    const destination = config.output_destinations.slack
    const configuredIntegration = destination
        ? integrations.find((integration) => integration.id === destination.integration_id)
        : undefined
    const selectedIntegration = configuredIntegration ?? (integrations.length === 1 ? integrations[0] : null)

    const selectWorkspace = (integrationId: number): void => {
        onUpdate(config.id, {
            output_destinations: { slack: { integration_id: integrationId, channel: null } },
        })
    }

    const selectChannel = (channel: string | null): void => {
        if (!channel || !selectedIntegration) {
            onUpdate(config.id, { output_destinations: {} })
            return
        }
        onUpdate(config.id, {
            output_destinations: {
                slack: { integration_id: selectedIntegration.id, channel },
            },
        })
    }

    return (
        <div className="flex flex-col gap-2 border-t border-primary pt-2">
            <div className="flex flex-col min-w-0">
                <span className="text-xs text-default">Slack destination</span>
                <span className="text-[11.5px] text-muted">Post each scout run's output to a channel</span>
            </div>
            {loading ? (
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
                            disabledReason={updating ? 'Saving…' : undefined}
                        />
                    ) : null}
                    {selectedIntegration ? (
                        <SlackChannelPicker
                            integration={selectedIntegration}
                            value={configuredIntegration ? (destination?.channel ?? undefined) : undefined}
                            onChange={selectChannel}
                            disabled={updating}
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

/**
 * Confirm-then-delete for a custom scout. Deletion archives the scout's skill (the permanent off
 * switch — the coordinator won't re-seed a tombstoned skill or re-create its config) and removes
 * its config. Irreversible, so the dialog steers users toward disable when they only want a pause.
 */
function confirmDeleteScout(config: SignalScoutConfig, onDelete: (configId: string) => void): void {
    const displayName = prettifyScoutSkillName(config.skill_name)
    LemonDialog.open({
        title: `Delete the ${displayName} scout?`,
        description: (
            <span>
                This archives the <span className="font-mono text-[11px]">{config.skill_name}</span> skill and removes
                its config. The scout stops running and won't come back — this can't be undone. To pause a scout without
                deleting it, disable it instead.
            </span>
        ),
        primaryButton: {
            children: 'Delete',
            status: 'danger',
            onClick: () => onDelete(config.id),
        },
        secondaryButton: { children: 'Cancel' },
    })
}
