import { useActions, useValues } from 'kea'

import {
    IconCalendar,
    IconInfo,
    IconList,
    IconPause,
    IconPencil,
    IconPlay,
    IconToggle,
    IconTrash,
} from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCalendarSelectInput,
    LemonCollapse,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTagType,
    Link,
} from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { hasFormErrors } from 'lib/utils/objects'
import { shortTimeZone } from 'lib/utils/timezones'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { groupsModel, Noun } from '~/models/groupsModel'
import {
    FeatureFlagType,
    MultivariateFlagVariant,
    RecurrenceInterval,
    ScheduledChangeOperationType,
    ScheduledChangeType,
} from '~/types'

import {
    describeCron,
    featureFlagLogic,
    PAIRED_PRESETS,
    validateFeatureFlagKey,
    variantKeyToIndexFeatureFlagPayloads,
} from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { groupFilters } from './FeatureFlags'
import { featureFlagScheduleEditLogic } from './featureFlagScheduleEditLogic'
import { FeatureFlagVariantsForm } from './FeatureFlagVariantsForm'

export const DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

/** Shows the project timezone abbreviation (e.g. "PST") with a tooltip linking to settings. */
function ScheduleTimezoneHint(): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    if (!currentTeam) {
        return null
    }
    const tz = shortTimeZone(currentTeam.timezone) ?? currentTeam.timezone
    return (
        <Tooltip
            interactive
            title={
                <>
                    Times are in the{' '}
                    <Link to={urls.settings('environment-customization', 'date-and-time')} target="_blank">
                        project's timezone
                    </Link>{' '}
                    ({currentTeam.timezone})
                </>
            }
        >
            <span className="text-muted font-normal">({tz})</span>
        </Tooltip>
    )
}

type AggregationLabel = (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun

/** A recurring schedule that has been paused retains its recurrence config but has is_recurring=false. */
function isSchedulePaused(sc: ScheduledChangeType): boolean {
    return !sc.is_recurring && (!!sc.recurrence_interval || !!sc.cron_expression)
}

function getScheduledVariantsPayloads(
    featureFlag: FeatureFlagType,
    schedulePayload: { variants?: MultivariateFlagVariant[]; payloads?: Record<string, any>; filters?: any }
): { variants: MultivariateFlagVariant[]; payloads: Record<string, any> } {
    const currentVariants = featureFlag.filters.multivariate?.variants || []
    const currentPayloads = featureFlag.filters.payloads || {}

    if (schedulePayload.variants && schedulePayload.variants.length > 0) {
        return {
            variants: schedulePayload.variants,
            payloads: schedulePayload.payloads || {},
        }
    }

    if (schedulePayload.payloads && Object.keys(schedulePayload.payloads).length > 0) {
        return {
            variants: currentVariants,
            payloads: schedulePayload.payloads,
        }
    }

    const transformedFlag = variantKeyToIndexFeatureFlagPayloads({
        ...featureFlag,
        filters: {
            ...featureFlag.filters,
            payloads: currentPayloads,
        },
    })

    return {
        variants: currentVariants,
        payloads: transformedFlag.filters.payloads || {},
    }
}

// --- Change type card definitions ---

interface ChangeTypeOption {
    value: ScheduledChangeOperationType
    label: string
    description: string
    icon: JSX.Element
}

const CHANGE_TYPE_OPTIONS: ChangeTypeOption[] = [
    {
        value: ScheduledChangeOperationType.UpdateStatus,
        label: 'Change status',
        description: 'Enable or disable the flag',
        icon: <IconToggle className="text-lg" />,
    },
    {
        value: ScheduledChangeOperationType.AddReleaseCondition,
        label: 'Add a condition',
        description: 'Append a new release condition',
        icon: <IconCalendar className="text-lg" />,
    },
    {
        value: ScheduledChangeOperationType.UpdateVariants,
        label: 'Update variants',
        description: 'Replace variant configuration',
        icon: <IconList className="text-lg" />,
    },
]

// Operations that support recurring schedules
const RECURRING_SUPPORTED_OPERATIONS = new Set([
    ScheduledChangeOperationType.UpdateStatus,
    ScheduledChangeOperationType.UpdateVariants,
])

// --- Schedule card for the list view ---

function ScheduleStatusTag({ scheduledChange }: { scheduledChange: ScheduledChangeType }): JSX.Element {
    const { executed_at, failure_reason, is_recurring } = scheduledChange
    const { currentTeam } = useValues(teamLogic)
    const tz = currentTeam?.timezone || 'UTC'

    function getStatus(): { type: LemonTagType; text: string; tooltip?: string } {
        if (failure_reason) {
            return { type: 'danger', text: 'Error', tooltip: `Failed: ${failure_reason}` }
        } else if (executed_at) {
            const executedAt = dayjs(executed_at)
            const tzShort = shortTimeZone(tz, executedAt.toDate()) ?? tz
            return {
                type: 'completion',
                text: 'Complete',
                tooltip: `Completed: ${executedAt.tz(tz).format('MMMM D, YYYY h:mm A')} (${tzShort})`,
            }
        } else if (isSchedulePaused(scheduledChange)) {
            return {
                type: 'warning',
                text: 'Paused',
                tooltip: 'Recurring schedule is paused. It will not execute until resumed.',
            }
        } else if (is_recurring) {
            return { type: 'highlight', text: 'Recurring' }
        }
        return { type: 'default', text: 'Scheduled' }
    }

    const { type, text, tooltip } = getStatus()
    return (
        <Tooltip title={tooltip}>
            <LemonTag type={type}>
                <b className="uppercase">{text}</b>
            </LemonTag>
        </Tooltip>
    )
}

function ChangeDescription({
    scheduledChange,
    aggregationLabel,
}: {
    scheduledChange: ScheduledChangeType
    aggregationLabel: AggregationLabel
}): JSX.Element {
    const { payload } = scheduledChange

    if (payload.operation === ScheduledChangeOperationType.UpdateStatus) {
        const isEnabled = payload.value
        return (
            <div className="flex items-center gap-2">
                <IconToggle className="text-muted" />
                <LemonTag type={isEnabled ? 'success' : 'default'} className="uppercase">
                    {isEnabled ? 'Enable' : 'Disable'}
                </LemonTag>
            </div>
        )
    }

    if (payload.operation === ScheduledChangeOperationType.AddReleaseCondition) {
        const releaseText = groupFilters(payload.value, undefined, aggregationLabel)
        return (
            <div className="flex items-center gap-2">
                <IconCalendar className="text-muted" />
                <span className="font-medium">Add condition:</span>
                {typeof releaseText === 'string' && releaseText.startsWith('100% of') ? (
                    <LemonTag type="highlight">{releaseText}</LemonTag>
                ) : (
                    releaseText
                )}
            </div>
        )
    }

    if (payload.operation === ScheduledChangeOperationType.UpdateVariants) {
        const variantCount = payload.value?.variants?.length || 0
        return (
            <div className="flex items-center gap-2">
                <IconList className="text-muted" />
                <span className="font-medium">Update variants:</span>
                <LemonTag type="highlight">
                    {variantCount} variant{variantCount !== 1 ? 's' : ''}
                </LemonTag>
            </div>
        )
    }

    return <span className="text-muted">{JSON.stringify(payload)}</span>
}

function ScheduleTiming({ scheduledChange }: { scheduledChange: ScheduledChangeType }): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const tz = currentTeam?.timezone || 'UTC'
    const scheduledAt = dayjs(scheduledChange.scheduled_at).tz(tz)
    const tzShort = shortTimeZone(tz, scheduledAt.toDate()) ?? tz
    const formattedDate = `${scheduledAt.format(DAYJS_FORMAT)} (${tzShort})`
    const timeStr = scheduledAt.format('h:mm A')

    // Determine the recurring description from either a cron expression or a fixed interval
    let recurringDescription: string | null = null

    if (scheduledChange.cron_expression) {
        recurringDescription = describeCron(scheduledChange.cron_expression)
    } else if (scheduledChange.recurrence_interval) {
        switch (scheduledChange.recurrence_interval) {
            case RecurrenceInterval.Daily:
                recurringDescription = `Every day at ${timeStr}`
                break
            case RecurrenceInterval.Weekly:
                recurringDescription = `Every ${scheduledAt.format('dddd')} at ${timeStr}`
                break
            case RecurrenceInterval.Monthly: {
                const dayOfMonth = scheduledAt.date()
                const dayText = dayOfMonth >= 29 ? 'last day' : scheduledAt.format('Do')
                recurringDescription = `Monthly on the ${dayText} at ${timeStr}`
                break
            }
            case RecurrenceInterval.Yearly:
                recurringDescription = `Yearly on ${scheduledAt.format('MMMM Do')} at ${timeStr}`
                break
            default:
                recurringDescription = `Every ${scheduledChange.recurrence_interval}`
        }
    }

    if (recurringDescription) {
        if (isSchedulePaused(scheduledChange)) {
            return (
                <Tooltip title={`Was: ${recurringDescription}. Resume to continue.`}>
                    <span className="text-muted line-through">{recurringDescription}</span>
                </Tooltip>
            )
        }

        const endDateStr = scheduledChange.end_date
            ? ` · Ends ${dayjs(scheduledChange.end_date).tz(tz).format('MMM D, YYYY')}`
            : ''
        return (
            <Tooltip title={`Next: ${formattedDate}${endDateStr}`}>
                <span>{recurringDescription}</span>
            </Tooltip>
        )
    }

    return <span>{formattedDate}</span>
}

function ScheduleCard({
    scheduledChange,
    aggregationLabel,
    canEdit,
    onDelete,
    onPause,
    onResume,
    onEdit,
}: {
    scheduledChange: ScheduledChangeType
    aggregationLabel: AggregationLabel
    canEdit: boolean
    onDelete: (id: number) => void
    onPause: (id: number) => void
    onResume: (id: number) => void
    onEdit: (schedule: ScheduledChangeType) => void
}): JSX.Element {
    const paused = isSchedulePaused(scheduledChange)
    const isCompleted = !!scheduledChange.executed_at

    return (
        <div
            className={`rounded border p-3 bg-bg-light flex items-center justify-between gap-4 ${isCompleted ? 'opacity-60' : ''}`}
        >
            <div className="flex flex-col gap-1 min-w-0 flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                    <ChangeDescription scheduledChange={scheduledChange} aggregationLabel={aggregationLabel} />
                    <ScheduleStatusTag scheduledChange={scheduledChange} />
                </div>
                <div className="text-xs text-muted">
                    <ScheduleTiming scheduledChange={scheduledChange} />
                </div>
                <div className="flex items-center gap-1.5 text-xs text-muted">
                    {scheduledChange.created_by && (
                        <>
                            <ProfilePicture user={scheduledChange.created_by} size="xs" />
                            <span>{scheduledChange.created_by.first_name || scheduledChange.created_by.email}</span>
                        </>
                    )}
                    {scheduledChange.created_at && (
                        <>
                            <span>·</span>
                            <TZLabel time={scheduledChange.created_at} />
                        </>
                    )}
                </div>
            </div>
            {!isCompleted && canEdit && (
                <div className="flex items-center gap-1 shrink-0">
                    <LemonButton
                        size="small"
                        icon={<IconPencil />}
                        tooltip="Edit"
                        onClick={() => onEdit(scheduledChange)}
                    />
                    {scheduledChange.is_recurring && (
                        <LemonButton
                            size="small"
                            icon={<IconPause />}
                            tooltip="Pause recurring"
                            onClick={() => onPause(scheduledChange.id)}
                        />
                    )}
                    {paused && (
                        <LemonButton
                            size="small"
                            icon={<IconPlay />}
                            tooltip="Resume recurring"
                            onClick={() => onResume(scheduledChange.id)}
                        />
                    )}
                    <LemonButton
                        size="small"
                        status="danger"
                        icon={<IconTrash />}
                        tooltip="Delete"
                        onClick={() => onDelete(scheduledChange.id)}
                    />
                </div>
            )}
        </div>
    )
}

export default function FeatureFlagSchedule(): JSX.Element {
    const {
        featureFlag,
        scheduledChangesLoading,
        scheduledChangeOperation,
        scheduleDateMarker,
        schedulePayload,
        schedulePayloadErrors,
        isRecurring,
        cronExpression,
        endDate,
        repeatsValue,
        cronPreview,
        activeSchedules,
        completedSchedules,
        schedulePreset,
        customPairEnableCron,
        customPairDisableCron,
        customPairEnableCronPreview,
        customPairDisableCronPreview,
        canCreatePairedSchedule,
    } = useValues(featureFlagLogic)
    const {
        deleteScheduledChange,
        setScheduleDateMarker,
        setSchedulePayload,
        setScheduledChangeOperation,
        createScheduledChange,
        setCronExpression,
        setRepeatsValue,
        setEndDate,
        stopRecurringScheduledChange,
        resumeRecurringScheduledChange,
        setSchedulePreset,
        setCustomPairCron,
        createPairedSchedule,
    } = useActions(featureFlagLogic)
    const {
        isEditOpen,
        editingSchedule,
        editScheduledAt,
        editCronExpression,
        editEndDate,
        editIsRecurring,
        editPayloadValue,
        editRepeatsValue,
        editCronPreview,
        editOperationType,
        hasEditChanges,
        editValidationErrors,
        editSaving,
    } = useValues(featureFlagScheduleEditLogic({ id: featureFlag.id ?? 'new' }))
    const {
        openEdit,
        closeEdit,
        setEditScheduledAt,
        setEditCronExpression,
        setEditEndDate,
        setEditPayloadValue,
        setEditRepeatsValue,
        saveEdit,
    } = useActions(featureFlagScheduleEditLogic({ id: featureFlag.id ?? 'new' }))
    const { aggregationLabel } = useValues(groupsModel)
    const { currentTeam } = useValues(teamLogic)
    const scheduleTimezone = currentTeam?.timezone || 'UTC'

    const aggregationGroupTypeIndex = featureFlag.filters.aggregation_group_type_index
    const scheduleFilters = { ...schedulePayload.filters, aggregation_group_type_index: aggregationGroupTypeIndex }

    const { variants: displayVariants, payloads: displayPayloads } = getScheduledVariantsPayloads(
        featureFlag,
        schedulePayload
    )

    const variantErrors = displayVariants.map(({ key: variantKey }) => ({
        key: validateFeatureFlagKey(variantKey),
    }))

    const supportsRecurring = RECURRING_SUPPORTED_OPERATIONS.has(scheduledChangeOperation)

    // UpdateVariants is only available for multivariate flags
    const availableOptions = CHANGE_TYPE_OPTIONS.filter(
        (opt) => opt.value !== ScheduledChangeOperationType.UpdateVariants || featureFlag.filters.multivariate
    )

    return (
        <div className="flex flex-col gap-4">
            {/* Creation form */}
            {featureFlag.can_edit ? (
                <div className="rounded border p-4 bg-bg-light flex flex-col gap-4">
                    <div>
                        <h3 className="font-semibold text-base mb-1">Schedule a change</h3>
                        <span className="text-sm text-muted">
                            Automatically change flag properties at a future point in time.
                        </span>
                    </div>

                    {/* Row 1: Change type + Date/Repeat controls */}
                    <div className="flex flex-wrap gap-3 items-start">
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-muted">Change type</label>
                            <LemonSelect<ScheduledChangeOperationType>
                                className="min-w-44"
                                value={scheduledChangeOperation}
                                onChange={(value) => value && setScheduledChangeOperation(value)}
                                options={availableOptions.map((opt) => ({
                                    value: opt.value,
                                    label: opt.label,
                                    icon: opt.icon,
                                }))}
                            />
                        </div>
                        {!schedulePreset && (
                            <div className="flex flex-col gap-1">
                                <label className="text-xs font-medium text-muted">
                                    {repeatsValue === 'cron' ? (
                                        <Tooltip title="Time is computed from the cron expression">
                                            <span>Next run</span>
                                        </Tooltip>
                                    ) : (
                                        <>
                                            Date and time <ScheduleTimezoneHint />
                                        </>
                                    )}
                                </label>
                                <LemonCalendarSelectInput
                                    value={scheduleDateMarker}
                                    onChange={(value) => {
                                        setScheduleDateMarker(value)
                                        if (repeatsValue === 'cron' && cronExpression && value) {
                                            // Re-snap to the next cron match from the newly picked date
                                            setCronExpression(cronExpression)
                                        }
                                    }}
                                    placeholder="Select date"
                                    selectionPeriod="upcoming"
                                    selectionPeriodTimezone={scheduleTimezone}
                                    granularity={repeatsValue === 'cron' ? 'day' : 'minute'}
                                    format={repeatsValue === 'cron' ? 'MMMM D, YYYY' : undefined}
                                    clearable
                                />
                            </div>
                        )}
                        {supportsRecurring && (
                            <>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Repeats</label>
                                    <LemonSelect
                                        className="min-w-36"
                                        value={schedulePreset ?? repeatsValue}
                                        onChange={(value) => {
                                            if (
                                                value === 'business_hours' ||
                                                value === 'weekdays_only' ||
                                                value === 'custom_pair'
                                            ) {
                                                setSchedulePreset(value)
                                            } else {
                                                setSchedulePreset(null)
                                                setRepeatsValue(value)
                                            }
                                        }}
                                        options={
                                            scheduledChangeOperation === ScheduledChangeOperationType.UpdateStatus
                                                ? [
                                                      {
                                                          title: 'Single schedule',
                                                          options: [
                                                              {
                                                                  value: 'none' as const,
                                                                  label: 'Does not repeat',
                                                              },
                                                              {
                                                                  value: RecurrenceInterval.Daily,
                                                                  label: 'Daily',
                                                              },
                                                              {
                                                                  value: RecurrenceInterval.Weekly,
                                                                  label: 'Weekly',
                                                              },
                                                              {
                                                                  value: RecurrenceInterval.Monthly,
                                                                  label: 'Monthly',
                                                              },
                                                              {
                                                                  value: RecurrenceInterval.Yearly,
                                                                  label: 'Yearly',
                                                              },
                                                              {
                                                                  value: 'cron' as const,
                                                                  label: 'Custom (cron)',
                                                              },
                                                          ],
                                                      },
                                                      {
                                                          title: 'Paired schedules',
                                                          options: [
                                                              {
                                                                  value: 'business_hours' as const,
                                                                  label: 'Business hours',
                                                              },
                                                              {
                                                                  value: 'weekdays_only' as const,
                                                                  label: 'Weekdays only',
                                                              },
                                                              {
                                                                  value: 'custom_pair' as const,
                                                                  label: 'Custom pair',
                                                              },
                                                          ],
                                                      },
                                                  ]
                                                : [
                                                      {
                                                          value: 'none' as const,
                                                          label: 'Does not repeat',
                                                      },
                                                      {
                                                          value: RecurrenceInterval.Daily,
                                                          label: 'Daily',
                                                      },
                                                      {
                                                          value: RecurrenceInterval.Weekly,
                                                          label: 'Weekly',
                                                      },
                                                      {
                                                          value: RecurrenceInterval.Monthly,
                                                          label: 'Monthly',
                                                      },
                                                      {
                                                          value: RecurrenceInterval.Yearly,
                                                          label: 'Yearly',
                                                      },
                                                      {
                                                          value: 'cron' as const,
                                                          label: 'Custom (cron)',
                                                      },
                                                  ]
                                        }
                                    />
                                </div>
                                {!schedulePreset && repeatsValue === 'cron' && (
                                    <div className="flex flex-col gap-1 min-w-48">
                                        <label className="text-xs font-medium text-muted">Cron expression</label>
                                        <LemonInput
                                            className="font-mono"
                                            value={cronExpression ?? ''}
                                            onChange={(value) => setCronExpression(value)}
                                            placeholder="0 9 * * 1-5"
                                        />
                                        {cronPreview && <span className="text-xs text-muted">{cronPreview}</span>}
                                    </div>
                                )}
                                {(isRecurring || !!schedulePreset) && (
                                    <div className="flex flex-col gap-1">
                                        <label className="text-xs font-medium text-muted flex items-center gap-1">
                                            Ends
                                            <Tooltip
                                                interactive
                                                title={
                                                    <>
                                                        Schedule will run through end of this day in the{' '}
                                                        <Link
                                                            to={urls.settings(
                                                                'environment-customization',
                                                                'date-and-time'
                                                            )}
                                                            target="_blank"
                                                        >
                                                            project's timezone
                                                        </Link>
                                                    </>
                                                }
                                            >
                                                <IconInfo className="text-muted text-base" />
                                            </Tooltip>
                                        </label>
                                        <LemonCalendarSelectInput
                                            value={endDate}
                                            onChange={(value) => setEndDate(value)}
                                            placeholder="Never"
                                            selectionPeriod="upcoming"
                                            selectionPeriodTimezone={scheduleTimezone}
                                            granularity="day"
                                            clearable
                                        />
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Paired preset summary */}
                    {schedulePreset && schedulePreset !== 'custom_pair' && (
                        <div className="rounded border p-4 flex flex-col gap-2">
                            <p className="text-sm font-medium m-0">
                                {PAIRED_PRESETS[schedulePreset as 'business_hours' | 'weekdays_only'].label}
                            </p>
                            <p className="text-muted text-sm m-0">
                                {PAIRED_PRESETS[schedulePreset as 'business_hours' | 'weekdays_only'].description}
                            </p>
                            <div className="flex gap-4">
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-xs font-medium text-success">Enable</span>
                                    <span className="text-xs text-muted font-mono">
                                        {
                                            PAIRED_PRESETS[schedulePreset as 'business_hours' | 'weekdays_only']
                                                .enableCron
                                        }
                                    </span>
                                    <span className="text-xs text-muted">
                                        {describeCron(
                                            PAIRED_PRESETS[schedulePreset as 'business_hours' | 'weekdays_only']
                                                .enableCron
                                        )}
                                    </span>
                                </div>
                                <div className="flex flex-col gap-0.5">
                                    <span className="text-xs font-medium text-danger">Disable</span>
                                    <span className="text-xs text-muted font-mono">
                                        {
                                            PAIRED_PRESETS[schedulePreset as 'business_hours' | 'weekdays_only']
                                                .disableCron
                                        }
                                    </span>
                                    <span className="text-xs text-muted">
                                        {describeCron(
                                            PAIRED_PRESETS[schedulePreset as 'business_hours' | 'weekdays_only']
                                                .disableCron
                                        )}
                                    </span>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Custom pair cron inputs */}
                    {schedulePreset === 'custom_pair' && (
                        <div className="rounded border p-4 flex flex-col gap-3">
                            <p className="text-sm font-medium m-0">Custom paired schedule</p>
                            <p className="text-muted text-sm m-0">
                                Enter two cron expressions: one to enable the flag and one to disable it.
                            </p>
                            <div className="flex gap-4">
                                <div className="flex flex-col gap-1 flex-1">
                                    <label className="text-xs font-medium text-success">Enable cron</label>
                                    <LemonInput
                                        className="font-mono"
                                        value={customPairEnableCron}
                                        onChange={(value) => setCustomPairCron('enable', value)}
                                        placeholder="0 9 * * 1-5"
                                    />
                                    {customPairEnableCronPreview && (
                                        <span className="text-xs text-muted">{customPairEnableCronPreview}</span>
                                    )}
                                </div>
                                <div className="flex flex-col gap-1 flex-1">
                                    <label className="text-xs font-medium text-danger">Disable cron</label>
                                    <LemonInput
                                        className="font-mono"
                                        value={customPairDisableCron}
                                        onChange={(value) => setCustomPairCron('disable', value)}
                                        placeholder="0 17 * * 1-5"
                                    />
                                    {customPairDisableCronPreview && (
                                        <span className="text-xs text-muted">{customPairDisableCronPreview}</span>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Row 2: Configuration panel */}
                    {!schedulePreset && scheduledChangeOperation === ScheduledChangeOperationType.UpdateStatus && (
                        <div className="rounded border p-4 flex flex-col gap-2">
                            <p className="text-muted text-sm m-0">
                                The flag will be <strong>{schedulePayload.active ? 'enabled' : 'disabled'}</strong>
                                {scheduleDateMarker ? (
                                    <>
                                        {` on ${scheduleDateMarker.format(DAYJS_FORMAT)} `}
                                        <ScheduleTimezoneHint />
                                    </>
                                ) : (
                                    ' on the scheduled date'
                                )}
                                .
                            </p>
                            <LemonSwitch
                                checked={!!schedulePayload.active}
                                onChange={(checked) => setSchedulePayload(null, checked)}
                                label={schedulePayload.active ? 'Flag will be enabled' : 'Flag will be disabled'}
                                bordered
                            />
                        </div>
                    )}
                    {scheduledChangeOperation === ScheduledChangeOperationType.AddReleaseCondition && (
                        <div className="flex flex-col gap-3">
                            <p className="text-muted text-sm m-0">
                                This condition will be appended to the flag's existing release conditions; it will not
                                replace them.
                            </p>
                            <div className="rounded border p-3">
                                <FeatureFlagReleaseConditionsCollapsible
                                    id={`schedule-release-conditions-${featureFlag.id}`}
                                    filters={scheduleFilters}
                                    onChange={(value, errors) => setSchedulePayload(value, null, errors, null, null)}
                                    hideMatchOptions
                                />
                            </div>
                        </div>
                    )}
                    {scheduledChangeOperation === ScheduledChangeOperationType.UpdateVariants &&
                        !!featureFlag.filters.multivariate && (
                            <div className="rounded border p-3">
                                <FeatureFlagVariantsForm
                                    variants={displayVariants}
                                    payloads={displayPayloads}
                                    onAddVariant={() => {
                                        const newVariants = [
                                            ...displayVariants,
                                            { key: '', name: '', rollout_percentage: 0 },
                                        ]
                                        setSchedulePayload(null, null, null, newVariants, displayPayloads)
                                    }}
                                    onRemoveVariant={(index) => {
                                        const newVariants = displayVariants.filter((_, i) => i !== index)
                                        const newPayloads = { ...displayPayloads }
                                        delete newPayloads[index]
                                        setSchedulePayload(null, null, null, newVariants, newPayloads)
                                    }}
                                    onDistributeEqually={() => {
                                        if (displayVariants.length === 0) {
                                            return
                                        }
                                        const equalPercentage = Math.floor(100 / displayVariants.length)
                                        const remainder = 100 - equalPercentage * displayVariants.length
                                        const distributedVariants = displayVariants.map((variant, index) => ({
                                            ...variant,
                                            rollout_percentage: equalPercentage + (index === 0 ? remainder : 0),
                                        }))
                                        setSchedulePayload(null, null, null, distributedVariants, displayPayloads)
                                    }}
                                    onVariantChange={(index, field, value) => {
                                        const newVariants = [...displayVariants]
                                        newVariants[index] = { ...newVariants[index], [field]: value }
                                        setSchedulePayload(null, null, null, newVariants, displayPayloads)
                                    }}
                                    onPayloadChange={(index, value) => {
                                        const newPayloads = { ...displayPayloads }
                                        if (value === undefined) {
                                            delete newPayloads[index]
                                        } else {
                                            newPayloads[index] = value
                                        }
                                        setSchedulePayload(null, null, null, displayVariants, newPayloads)
                                    }}
                                    variantErrors={variantErrors}
                                />
                            </div>
                        )}

                    {/* Warning for recurring variant updates */}
                    {isRecurring &&
                        scheduledChangeOperation === ScheduledChangeOperationType.UpdateVariants &&
                        !!featureFlag.filters.multivariate && (
                            <LemonBanner type="warning">
                                This will reset variants to the configuration above on each recurrence. Any manual
                                changes made between runs will be overwritten.
                            </LemonBanner>
                        )}

                    {/* Hint when creating a single recurring schedule with no other active schedules */}
                    {isRecurring && !schedulePreset && activeSchedules.length === 0 && (
                        <LemonBanner type="info">
                            Recurring schedules work best when paired with a complementary schedule. For example, enable
                            the flag on weekday mornings and disable it on Friday evenings. Try the "Paired schedules"
                            presets in the Repeats dropdown above.
                        </LemonBanner>
                    )}

                    <div className="flex items-center justify-end">
                        {schedulePreset ? (
                            <LemonButton
                                type="primary"
                                onClick={createPairedSchedule}
                                disabledReason={
                                    !canCreatePairedSchedule
                                        ? schedulePreset === 'custom_pair'
                                            ? 'Enter valid enable and disable cron expressions'
                                            : undefined
                                        : undefined
                                }
                            >
                                Schedule pair
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                onClick={createScheduledChange}
                                disabledReason={
                                    !scheduleDateMarker
                                        ? 'Select the scheduled date and time'
                                        : isRecurring && repeatsValue === 'none'
                                          ? 'Select a repeat interval'
                                          : isRecurring && cronExpression !== null && cronExpression.trim() === ''
                                            ? 'Enter a cron expression'
                                            : repeatsValue === 'cron' && cronPreview === 'Invalid cron expression'
                                              ? 'Enter a valid cron expression'
                                              : hasFormErrors(schedulePayloadErrors)
                                                ? 'Fix release condition errors'
                                                : scheduledChangeOperation ===
                                                        ScheduledChangeOperationType.UpdateVariants &&
                                                    variantErrors.some((error) => error.key != null)
                                                  ? 'Fix schedule variant changes errors'
                                                  : undefined
                                }
                            >
                                Schedule
                            </LemonButton>
                        )}
                    </div>
                </div>
            ) : (
                <LemonBanner type="info">
                    You don't have the necessary permissions to schedule changes to this flag. Contact your
                    administrator to request editing rights.
                </LemonBanner>
            )}

            {/* Schedule list */}
            {activeSchedules.length > 0 && (
                <div className="flex flex-col gap-2">
                    <h3 className="font-semibold text-base">
                        Active & upcoming
                        <span className="text-muted font-normal ml-1">({activeSchedules.length})</span>
                    </h3>
                    <div className="flex flex-col gap-2">
                        {activeSchedules.map((sc: ScheduledChangeType) => (
                            <ScheduleCard
                                key={sc.id}
                                scheduledChange={sc}
                                aggregationLabel={aggregationLabel}
                                canEdit={featureFlag.can_edit}
                                onDelete={deleteScheduledChange}
                                onPause={stopRecurringScheduledChange}
                                onResume={resumeRecurringScheduledChange}
                                onEdit={openEdit}
                            />
                        ))}
                    </div>
                </div>
            )}

            {completedSchedules.length > 0 && (
                <LemonCollapse
                    className="bg-bg-light"
                    panels={[
                        {
                            key: 'history',
                            header: `History (${completedSchedules.length})`,
                            content: (
                                <div className="flex flex-col gap-2">
                                    {completedSchedules.map((sc: ScheduledChangeType) => (
                                        <ScheduleCard
                                            key={sc.id}
                                            scheduledChange={sc}
                                            aggregationLabel={aggregationLabel}
                                            canEdit={false}
                                            onDelete={deleteScheduledChange}
                                            onPause={stopRecurringScheduledChange}
                                            onResume={resumeRecurringScheduledChange}
                                            onEdit={openEdit}
                                        />
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                />
            )}

            {!scheduledChangesLoading && activeSchedules.length === 0 && completedSchedules.length === 0 && (
                <div className="rounded border border-dashed p-6 flex flex-col items-center gap-2 text-center">
                    <span className="text-muted text-sm">No scheduled changes yet</span>
                    {featureFlag.can_edit && (
                        <span className="text-muted text-xs">
                            Use the form above to schedule flag changes for a future date.
                        </span>
                    )}
                </div>
            )}

            {/* Edit modal */}
            <LemonModal
                isOpen={isEditOpen}
                onClose={closeEdit}
                title="Edit scheduled change"
                footer={
                    <>
                        <LemonButton onClick={closeEdit}>Cancel</LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveEdit}
                            loading={editSaving}
                            disabledReason={
                                !hasEditChanges
                                    ? 'No changes to save'
                                    : Object.keys(editValidationErrors).length > 0
                                      ? String(Object.values(editValidationErrors)[0])
                                      : undefined
                            }
                        >
                            Save changes
                        </LemonButton>
                    </>
                }
            >
                <div className="flex flex-col gap-4">
                    {editOperationType === ScheduledChangeOperationType.UpdateStatus && (
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-muted">Status</label>
                            <LemonSwitch
                                checked={editPayloadValue}
                                onChange={(checked) => setEditPayloadValue(checked)}
                                label={editPayloadValue ? 'Flag will be enabled' : 'Flag will be disabled'}
                                bordered
                            />
                        </div>
                    )}

                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-muted">
                            {editRepeatsValue === 'cron' ? (
                                'Next run'
                            ) : (
                                <>
                                    Date and time <ScheduleTimezoneHint />
                                </>
                            )}
                        </label>
                        <LemonCalendarSelectInput
                            value={editScheduledAt}
                            onChange={(value) => {
                                setEditScheduledAt(value)
                                if (editRepeatsValue === 'cron' && editCronExpression && value) {
                                    // Re-snap to the next cron match from the newly picked date
                                    setEditCronExpression(editCronExpression)
                                }
                            }}
                            placeholder="Select date"
                            selectionPeriod="upcoming"
                            selectionPeriodTimezone={scheduleTimezone}
                            granularity={editRepeatsValue === 'cron' ? 'day' : 'minute'}
                            format={editRepeatsValue === 'cron' ? 'MMMM D, YYYY' : undefined}
                            clearable
                        />
                        {editValidationErrors.scheduledAt && (
                            <span className="text-xs text-danger">{editValidationErrors.scheduledAt}</span>
                        )}
                    </div>

                    <div className="flex flex-col gap-1">
                        <label className="text-xs font-medium text-muted">Repeats</label>
                        <LemonSelect
                            className="min-w-36"
                            value={editRepeatsValue}
                            onChange={setEditRepeatsValue}
                            options={[
                                { value: 'none' as const, label: 'Does not repeat' },
                                { value: RecurrenceInterval.Daily, label: 'Daily' },
                                { value: RecurrenceInterval.Weekly, label: 'Weekly' },
                                { value: RecurrenceInterval.Monthly, label: 'Monthly' },
                                { value: RecurrenceInterval.Yearly, label: 'Yearly' },
                                { value: 'cron' as const, label: 'Custom (cron)' },
                            ]}
                        />
                    </div>

                    {editRepeatsValue === 'cron' && (
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-muted">Cron expression</label>
                            <LemonInput
                                className="font-mono"
                                value={editCronExpression ?? ''}
                                onChange={(value) => setEditCronExpression(value)}
                                placeholder="0 9 * * 1-5"
                            />
                            {editValidationErrors.cronExpression ? (
                                <span className="text-xs text-danger">{editValidationErrors.cronExpression}</span>
                            ) : (
                                editCronPreview && <span className="text-xs text-muted">{editCronPreview}</span>
                            )}
                        </div>
                    )}

                    {editIsRecurring && (
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-muted">Ends</label>
                            <LemonCalendarSelectInput
                                value={editEndDate}
                                onChange={(value) => setEditEndDate(value)}
                                placeholder="Never"
                                selectionPeriod="upcoming"
                                selectionPeriodTimezone={scheduleTimezone}
                                granularity="day"
                                clearable
                            />
                            {editValidationErrors.endDate && (
                                <span className="text-xs text-danger">{editValidationErrors.endDate}</span>
                            )}
                        </div>
                    )}

                    {editingSchedule?.payload.operation === ScheduledChangeOperationType.AddReleaseCondition && (
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-muted">Release condition</label>
                            <div className="rounded border p-2 bg-bg-light text-sm">
                                {groupFilters(editingSchedule.payload.value, undefined, aggregationLabel)}
                            </div>
                            <span className="text-xs text-muted">
                                To change the release condition, delete this schedule and create a new one.
                            </span>
                        </div>
                    )}
                </div>
            </LemonModal>
        </div>
    )
}
