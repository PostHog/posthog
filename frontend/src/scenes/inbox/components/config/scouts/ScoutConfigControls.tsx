import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { SignalScoutConfig, SignalScoutConfigUpdate } from '../../../types'
import { formatRunInterval, prettifyScoutSkillName, RUN_INTERVAL_OPTIONS } from '../../../utils/scoutRunsWindow'

interface ScoutConfigControlsProps {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
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
export function ScoutEnabledSwitch({ config, onUpdate }: ScoutConfigControlsProps): JSX.Element {
    return (
        <Tooltip title={config.enabled ? 'Disable scout' : 'Enable scout'}>
            <span>
                <LemonSwitch
                    size="small"
                    checked={config.enabled}
                    onChange={(checked) => onUpdate(config.id, { enabled: checked })}
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
}: ScoutConfigControlsProps & { onDelete?: (configId: string) => void }): JSX.Element {
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
                    disabledReason={config.enabled ? undefined : 'Enable the scout first'}
                    className="w-36"
                    onChange={(value) => onUpdate(config.id, { run_interval_minutes: Number(value) })}
                />
            </div>
            {onDelete ? (
                <div className="flex items-center justify-between gap-4 border-t border-primary pt-2">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Delete scout</span>
                        <span className="text-[11.5px] text-muted">Remove this scout's config outright</span>
                    </div>
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={() => confirmDeleteScout(config, onDelete)}
                    >
                        Delete
                    </LemonButton>
                </div>
            ) : null}
        </div>
    )
}

/**
 * Confirm-then-delete for a scout config. The copy is honest about the caveat: deletion only
 * sticks for an orphaned config whose skill is gone — a live scout's config is re-created by the
 * coordinator on its next tick, so disabling is the way to stop one that still has a skill.
 */
function confirmDeleteScout(config: SignalScoutConfig, onDelete: (configId: string) => void): void {
    const displayName = prettifyScoutSkillName(config.skill_name)
    LemonDialog.open({
        title: `Delete the ${displayName} scout?`,
        description: (
            <span>
                This removes the config row outright. It's meant for cleaning up an orphaned scout whose skill was
                archived or deleted. If the <span className="font-mono text-[11px]">{config.skill_name}</span> skill
                still exists, the coordinator re-creates a default-schedule config on its next tick — to stop a live
                scout, disable it instead.
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
