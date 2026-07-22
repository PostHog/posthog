import { useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonInput, LemonSelect, LemonSwitch, Tooltip } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import {
    dailyCronToTime,
    formatRunInterval,
    prettifyScoutSkillName,
    RUN_INTERVAL_OPTIONS,
    timeToDailyCron,
} from '../../../utils/scoutRunsWindow'

interface ScoutConfigControlsProps {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
}

interface ScoutConfigFormProps extends ScoutConfigControlsProps {
    onDelete?: (configId: string) => void
    /** True while this scout's delete request is in flight — disables the delete button. */
    deleting?: boolean
    /** True while this scout's config update request is in flight. */
    updating?: boolean
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
export function ScoutEnabledSwitch({
    config,
    onUpdate,
    updating = false,
}: ScoutConfigControlsProps & { updating?: boolean }): JSX.Element {
    return (
        <Tooltip title={config.enabled ? 'Disable scout' : 'Enable scout'}>
            <span>
                <LemonSwitch
                    size="small"
                    checked={config.enabled}
                    onChange={(checked) => onUpdate(config.id, { enabled: checked })}
                    disabledReason={updating ? 'Saving scout settings' : undefined}
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
    const { timezone: projectTimezone } = useValues(teamLogic)
    const dailyTime = dailyCronToTime(config.run_cron_schedule)
    // A cron the simple time picker can't express (e.g. "0 9 * * 1-5", set via the API) — shown
    // as-is, and never silently overwritten by an untouched picker.
    const hasCustomCron = Boolean(config.run_cron_schedule) && dailyTime === null

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
                    disabledReason={
                        updating ? 'Saving scout settings' : config.enabled ? undefined : 'Enable the scout first'
                    }
                    className="w-36"
                    onChange={(value) => {
                        const runIntervalMinutes = Number(value)
                        onUpdate(config.id, {
                            run_interval_minutes: runIntervalMinutes,
                            ...(runIntervalMinutes === 1440 ? {} : { run_cron_schedule: null }),
                        })
                    }}
                />
            </div>
            {config.run_interval_minutes === 1440 ? (
                <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Daily run time</span>
                        <span className="text-[11.5px] text-muted">
                            {hasCustomCron
                                ? `Custom schedule "${config.run_cron_schedule}" (set via API)`
                                : `Optional. Uses the project timezone (${projectTimezone})`}
                        </span>
                    </div>
                    <LemonInput
                        key={config.run_cron_schedule ?? 'unset'}
                        type="time"
                        step={60}
                        size="small"
                        defaultValue={dailyTime ?? ''}
                        disabledReason={
                            updating ? 'Saving scout settings' : config.enabled ? undefined : 'Enable the scout first'
                        }
                        className="w-36"
                        onBlur={(event) => {
                            const value = event.currentTarget.value
                            if (!value && hasCustomCron) {
                                return
                            }
                            const runCronSchedule = value ? timeToDailyCron(value) : null
                            if (runCronSchedule !== config.run_cron_schedule) {
                                onUpdate(config.id, { run_cron_schedule: runCronSchedule })
                            }
                        }}
                    />
                </div>
            ) : null}
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
