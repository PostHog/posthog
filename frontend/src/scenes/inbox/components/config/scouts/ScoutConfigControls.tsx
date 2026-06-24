import { LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { SignalScoutConfig, SignalScoutConfigUpdate } from '../../../types'
import { formatRunInterval, RUN_INTERVAL_OPTIONS } from '../../../utils/scoutRunsWindow'

const MODE_OPTIONS = [
    { value: 'live', label: 'Live' },
    { value: 'dry_run', label: 'Dry run' },
]

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
export function ScoutConfigForm({ config, onUpdate }: ScoutConfigControlsProps): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Mode</span>
                    <span className="text-[11.5px] text-muted">
                        Dry run executes the scout but holds back its findings
                    </span>
                </div>
                <LemonSelect
                    size="small"
                    value={config.emit ? 'live' : 'dry_run'}
                    options={MODE_OPTIONS}
                    disabledReason={config.enabled ? undefined : 'Enable the scout first'}
                    className="w-24"
                    onChange={(value) => onUpdate(config.id, { emit: value === 'live' })}
                />
            </div>
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
        </div>
    )
}
