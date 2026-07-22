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

/** Sentinel select values for the scheduled (cron) modes — rolling options use the interval minutes. */
const DAILY_AT_MODE = 'daily_at'
const CUSTOM_CRON_MODE = 'custom_cron'
const DEFAULT_DAILY_TIME = '09:00'

/**
 * The schedule is either a rolling interval OR a cron — one select models that choice.
 * Rolling presets carry the interval minutes; "Daily at a set time" switches to a daily cron
 * (revealing the time picker); a cron the picker can't express shows as a read-only "Custom" mode.
 */
function scheduleOptions(config: SignalScoutConfig, scheduleMode: string): { value: string; label: string }[] {
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
    options.push({ value: DAILY_AT_MODE, label: 'Daily at a set time' })
    if (scheduleMode === CUSTOM_CRON_MODE) {
        options.push({ value: CUSTOM_CRON_MODE, label: `Custom (${config.run_cron_schedule})` })
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
    const scheduleMode = config.run_cron_schedule
        ? dailyTime !== null
            ? DAILY_AT_MODE
            : CUSTOM_CRON_MODE
        : String(config.run_interval_minutes)
    const controlsDisabledReason = updating
        ? 'Saving scout settings'
        : config.enabled
          ? undefined
          : 'Enable the scout first'

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-4">
                <div className="flex flex-col min-w-0">
                    <span className="text-xs text-default">Schedule</span>
                    <span className="text-[11.5px] text-muted">
                        {scheduleMode === CUSTOM_CRON_MODE
                            ? 'A cron schedule set via the API'
                            : 'A rolling cadence, or a set time each day'}
                    </span>
                </div>
                <LemonSelect
                    size="small"
                    value={scheduleMode}
                    options={scheduleOptions(config, scheduleMode)}
                    disabledReason={controlsDisabledReason}
                    className="w-44"
                    onChange={(value) => {
                        if (value === scheduleMode || value === CUSTOM_CRON_MODE) {
                            return
                        }
                        if (value === DAILY_AT_MODE) {
                            onUpdate(config.id, { run_cron_schedule: timeToDailyCron(dailyTime ?? DEFAULT_DAILY_TIME) })
                            return
                        }
                        // A rolling cadence replaces any cron — the schedule is one or the other.
                        onUpdate(config.id, { run_interval_minutes: Number(value), run_cron_schedule: null })
                    }}
                />
            </div>
            {scheduleMode === DAILY_AT_MODE ? (
                <div className="flex items-center justify-between gap-4">
                    <div className="flex flex-col min-w-0">
                        <span className="text-xs text-default">Run time</span>
                        <span className="text-[11.5px] text-muted">Uses the project timezone ({projectTimezone})</span>
                    </div>
                    <LemonInput
                        key={config.run_cron_schedule ?? 'unset'}
                        type="time"
                        step={60}
                        size="small"
                        defaultValue={dailyTime ?? DEFAULT_DAILY_TIME}
                        disabledReason={controlsDisabledReason}
                        className="w-44"
                        onBlur={(event) => {
                            const value = event.currentTarget.value
                            // Empty means a half-finished edit, never "clear" — turning the
                            // schedule off is the select's job, so just fall back to the saved time.
                            if (!value) {
                                return
                            }
                            const runCronSchedule = timeToDailyCron(value)
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
