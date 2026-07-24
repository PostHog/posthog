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
    DEFAULT_SCOUT_DAILY_TIME,
    getScoutScheduleMode,
    getScoutScheduleOptions,
    prettifyScoutSkillName,
    SCOUT_CUSTOM_CRON_SCHEDULE_MODE,
    SCOUT_DAILY_AT_SCHEDULE_MODE,
    timeToDailyCron,
} from '../../../utils/scoutRunsWindow'
import { ScoutSlackDestination } from './ScoutSlackDestination'

interface ScoutConfigControlsProps {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}

interface ScoutConfigFormProps extends ScoutConfigControlsProps {
    onDelete?: (configId: string) => void
    /** True while this scout's delete request is in flight — disables the delete button. */
    deleting?: boolean
    /** True while this scout's config update request is in flight. */
    updating?: boolean
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
    const scheduleMode = getScoutScheduleMode(config)
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
                        {scheduleMode === SCOUT_CUSTOM_CRON_SCHEDULE_MODE
                            ? 'A cron schedule set via the API'
                            : 'A rolling cadence, or a set time each day'}
                    </span>
                </div>
                <LemonSelect
                    size="small"
                    value={scheduleMode}
                    options={getScoutScheduleOptions(config)}
                    disabledReason={controlsDisabledReason}
                    className="w-44"
                    onChange={(value) => {
                        if (value === scheduleMode || value === SCOUT_CUSTOM_CRON_SCHEDULE_MODE) {
                            return
                        }
                        if (value === SCOUT_DAILY_AT_SCHEDULE_MODE) {
                            onUpdate(config.id, {
                                run_cron_schedule: timeToDailyCron(dailyTime ?? DEFAULT_SCOUT_DAILY_TIME),
                            })
                            return
                        }
                        // A rolling cadence replaces any cron — the schedule is one or the other.
                        onUpdate(config.id, { run_interval_minutes: Number(value), run_cron_schedule: null })
                    }}
                />
            </div>
            {scheduleMode === SCOUT_DAILY_AT_SCHEDULE_MODE ? (
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
                        defaultValue={dailyTime ?? DEFAULT_SCOUT_DAILY_TIME}
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
            <ScoutSlackDestination
                destination={config.output_destinations?.slack}
                onChange={(outputDestinations) => onUpdate(config.id, { output_destinations: outputDestinations })}
                disabledReason={controlsDisabledReason}
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
