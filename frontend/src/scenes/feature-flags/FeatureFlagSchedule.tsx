import { useActions, useValues } from 'kea'

import { IconCalendar, IconInfo, IconList, IconPause, IconPlay, IconToggle, IconTrash } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCalendarSelectInput,
    LemonCollapse,
    LemonSelect,
    LemonSwitch,
    LemonTag,
    LemonTagType,
    Link,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors } from 'lib/utils'
import { urls } from 'scenes/urls'

import { groupsModel, Noun } from '~/models/groupsModel'
import {
    FeatureFlagType,
    MultivariateFlagVariant,
    RecurrenceInterval,
    ScheduledChangeOperationType,
    ScheduledChangeType,
} from '~/types'

import { featureFlagLogic, validateFeatureFlagKey, variantKeyToIndexFeatureFlagPayloads } from './featureFlagLogic'
import { FeatureFlagReleaseConditionsCollapsible } from './FeatureFlagReleaseConditionsCollapsible'
import { groupFilters } from './FeatureFlags'
import { FeatureFlagVariantsForm } from './FeatureFlagVariantsForm'

export const DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

type AggregationLabel = (groupTypeIndex: number | null | undefined, deferToUserWording?: boolean) => Noun

/** A recurring schedule that has been paused retains its recurrence_interval but has is_recurring=false. */
function isSchedulePaused(sc: ScheduledChangeType): boolean {
    return !sc.is_recurring && !!sc.recurrence_interval
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

    function getStatus(): { type: LemonTagType; text: string; tooltip?: string } {
        if (failure_reason) {
            return { type: 'danger', text: 'Error', tooltip: `Failed: ${failure_reason}` }
        } else if (executed_at) {
            return {
                type: 'completion',
                text: 'Complete',
                tooltip: `Completed: ${dayjs(executed_at).format('MMMM D, YYYY h:mm A')}`,
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
    const scheduledAt = dayjs(scheduledChange.scheduled_at)
    const formattedDate = scheduledAt.format(DAYJS_FORMAT)
    const timeStr = scheduledAt.format('h:mm A')

    if (scheduledChange.recurrence_interval) {
        let recurringDescription: string
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

        if (isSchedulePaused(scheduledChange)) {
            return (
                <Tooltip title={`Was: ${recurringDescription}. Resume to continue.`}>
                    <span className="text-muted line-through">{recurringDescription}</span>
                </Tooltip>
            )
        }

        const endDateStr = scheduledChange.end_date
            ? ` · Ends ${dayjs(scheduledChange.end_date).format('MMM D, YYYY')}`
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
}: {
    scheduledChange: ScheduledChangeType
    aggregationLabel: AggregationLabel
    canEdit: boolean
    onDelete: (id: number) => void
    onPause: (id: number) => void
    onResume: (id: number) => void
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
            </div>
            {!isCompleted && canEdit && (
                <div className="flex items-center gap-1 shrink-0">
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

// --- Main component ---

export default function FeatureFlagSchedule(): JSX.Element {
    const {
        featureFlag,
        scheduledChanges,
        scheduledChangeOperation,
        scheduleDateMarker,
        schedulePayload,
        schedulePayloadErrors,
        isRecurring,
        recurrenceInterval,
        endDate,
    } = useValues(featureFlagLogic)
    const {
        deleteScheduledChange,
        setScheduleDateMarker,
        setSchedulePayload,
        setScheduledChangeOperation,
        createScheduledChange,
        setIsRecurring,
        setRecurrenceInterval,
        setEndDate,
        stopRecurringScheduledChange,
        resumeRecurringScheduledChange,
    } = useActions(featureFlagLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { featureFlags } = useValues(enabledFeaturesLogic)

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

    // Partition schedules into groups
    const activeRecurring = scheduledChanges.filter((sc: ScheduledChangeType) => sc.is_recurring && !sc.executed_at)
    const pausedRecurring = scheduledChanges.filter(
        (sc: ScheduledChangeType) => isSchedulePaused(sc) && !sc.executed_at
    )
    const upcomingOneTime = scheduledChanges.filter(
        (sc: ScheduledChangeType) => !sc.is_recurring && !sc.recurrence_interval && !sc.executed_at
    )
    const completed = scheduledChanges.filter((sc: ScheduledChangeType) => !!sc.executed_at)

    const activeSchedules = [...activeRecurring, ...pausedRecurring, ...upcomingOneTime]

    // Available change type options (gate UpdateVariants behind feature flag)
    const availableOptions = CHANGE_TYPE_OPTIONS.filter(
        (opt) =>
            opt.value !== ScheduledChangeOperationType.UpdateVariants ||
            (featureFlags[FEATURE_FLAGS.SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE] && featureFlag.filters.multivariate)
    )

    // Single "Repeats" dropdown: "Does not repeat" maps to isRecurring=false, intervals map to isRecurring=true
    const repeatsValue = isRecurring && recurrenceInterval ? recurrenceInterval : ('none' as const)

    const handleRepeatsChange = (value: RecurrenceInterval | 'none'): void => {
        if (value === 'none') {
            setIsRecurring(false)
            setRecurrenceInterval(null)
            setEndDate(null)
        } else {
            setIsRecurring(true)
            setRecurrenceInterval(value)
        }
    }

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
                    <div className="flex flex-wrap gap-3 items-end">
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
                        <div className="flex flex-col gap-1">
                            <label className="text-xs font-medium text-muted">Date and time</label>
                            <LemonCalendarSelectInput
                                value={scheduleDateMarker}
                                onChange={(value) => setScheduleDateMarker(value)}
                                placeholder="Select date"
                                selectionPeriod="upcoming"
                                granularity="minute"
                                clearable
                            />
                        </div>
                        {supportsRecurring && (
                            <>
                                <div className="flex flex-col gap-1">
                                    <label className="text-xs font-medium text-muted">Repeats</label>
                                    <LemonSelect
                                        className="min-w-36"
                                        value={repeatsValue}
                                        onChange={handleRepeatsChange}
                                        options={[
                                            { value: 'none' as const, label: 'Does not repeat' },
                                            { value: RecurrenceInterval.Daily, label: 'Daily' },
                                            { value: RecurrenceInterval.Weekly, label: 'Weekly' },
                                            { value: RecurrenceInterval.Monthly, label: 'Monthly' },
                                            { value: RecurrenceInterval.Yearly, label: 'Yearly' },
                                        ]}
                                    />
                                </div>
                                {isRecurring && (
                                    <div className="flex flex-col gap-1">
                                        <label className="text-xs font-medium text-muted flex items-center gap-1">
                                            Ends
                                            <Tooltip
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
                                            granularity="day"
                                            clearable
                                        />
                                    </div>
                                )}
                            </>
                        )}
                    </div>

                    {/* Row 2: Configuration panel */}
                    {scheduledChangeOperation === ScheduledChangeOperationType.UpdateStatus && (
                        <div className="self-start">
                            <LemonSwitch
                                checked={!!schedulePayload.active}
                                onChange={(checked) => setSchedulePayload(null, checked)}
                                label="Enable feature flag"
                                bordered
                            />
                        </div>
                    )}
                    {scheduledChangeOperation === ScheduledChangeOperationType.AddReleaseCondition && (
                        <div className="flex flex-col gap-3">
                            <LemonBanner type="info">
                                This condition will be appended to the flag's existing release conditions, not replace
                                them.
                            </LemonBanner>
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
                        featureFlags[FEATURE_FLAGS.SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE] && (
                            <div className="rounded border p-3">
                                <FeatureFlagVariantsForm
                                    variants={displayVariants}
                                    payloads={displayPayloads}
                                    onAddVariant={() => {
                                        const { variants: currentVariants, payloads: currentPayloads } =
                                            getScheduledVariantsPayloads(featureFlag, schedulePayload)
                                        const newVariants = [
                                            ...currentVariants,
                                            { key: '', name: '', rollout_percentage: 0 },
                                        ]
                                        setSchedulePayload(null, null, null, newVariants, currentPayloads)
                                    }}
                                    onRemoveVariant={(index) => {
                                        const { variants: currentVariants, payloads: currentPayloads } =
                                            getScheduledVariantsPayloads(featureFlag, schedulePayload)
                                        const newVariants = currentVariants.filter((_, i) => i !== index)
                                        const newPayloads = { ...currentPayloads }
                                        delete newPayloads[index]
                                        setSchedulePayload(null, null, null, newVariants, newPayloads)
                                    }}
                                    onDistributeEqually={() => {
                                        const { variants: currentVariants, payloads: currentPayloads } =
                                            getScheduledVariantsPayloads(featureFlag, schedulePayload)
                                        const equalPercentage = Math.floor(100 / currentVariants.length)
                                        const remainder = 100 - equalPercentage * currentVariants.length
                                        const distributedVariants = currentVariants.map((variant, index) => ({
                                            ...variant,
                                            rollout_percentage: equalPercentage + (index === 0 ? remainder : 0),
                                        }))
                                        setSchedulePayload(null, null, null, distributedVariants, currentPayloads)
                                    }}
                                    onVariantChange={(index, field, value) => {
                                        const { variants: currentVariants, payloads: currentPayloads } =
                                            getScheduledVariantsPayloads(featureFlag, schedulePayload)
                                        const newVariants = [...currentVariants]
                                        newVariants[index] = { ...newVariants[index], [field]: value }
                                        setSchedulePayload(null, null, null, newVariants, currentPayloads)
                                    }}
                                    onPayloadChange={(index, value) => {
                                        const { variants: currentVariants, payloads: currentPayloads } =
                                            getScheduledVariantsPayloads(featureFlag, schedulePayload)
                                        const newPayloads = { ...currentPayloads }
                                        if (value === undefined) {
                                            delete newPayloads[index]
                                        } else {
                                            newPayloads[index] = value
                                        }
                                        setSchedulePayload(null, null, null, currentVariants, newPayloads)
                                    }}
                                    variantErrors={variantErrors}
                                />
                            </div>
                        )}

                    {/* Warning for recurring variant updates */}
                    {isRecurring && scheduledChangeOperation === ScheduledChangeOperationType.UpdateVariants && (
                        <LemonBanner type="warning">
                            This will reset variants to the configuration above on each recurrence. Any manual changes
                            made between runs will be overwritten.
                        </LemonBanner>
                    )}

                    <div className="flex items-center justify-end">
                        <LemonButton
                            type="primary"
                            onClick={createScheduledChange}
                            disabledReason={
                                !scheduleDateMarker
                                    ? 'Select the scheduled date and time'
                                    : isRecurring && !recurrenceInterval
                                      ? 'Select a repeat interval'
                                      : hasFormErrors(schedulePayloadErrors)
                                        ? 'Fix release condition errors'
                                        : scheduledChangeOperation === ScheduledChangeOperationType.UpdateVariants &&
                                            variantErrors.some((error) => error.key != null)
                                          ? 'Fix schedule variant changes errors'
                                          : undefined
                            }
                        >
                            Schedule
                        </LemonButton>
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
                            />
                        ))}
                    </div>
                </div>
            )}

            {completed.length > 0 && (
                <LemonCollapse
                    className="bg-bg-light"
                    panels={[
                        {
                            key: 'history',
                            header: `History (${completed.length})`,
                            content: (
                                <div className="flex flex-col gap-2">
                                    {completed.map((sc: ScheduledChangeType) => (
                                        <ScheduleCard
                                            key={sc.id}
                                            scheduledChange={sc}
                                            aggregationLabel={aggregationLabel}
                                            canEdit={false}
                                            onDelete={deleteScheduledChange}
                                            onPause={stopRecurringScheduledChange}
                                            onResume={resumeRecurringScheduledChange}
                                        />
                                    ))}
                                </div>
                            ),
                        },
                    ]}
                />
            )}

            {activeSchedules.length === 0 && completed.length === 0 && (
                <div className="rounded border border-dashed p-6 flex flex-col items-center gap-2 text-center">
                    <span className="text-muted text-sm">No scheduled changes yet</span>
                    {featureFlag.can_edit && (
                        <span className="text-muted text-xs">
                            Use the form above to schedule flag changes for a future date.
                        </span>
                    )}
                </div>
            )}
        </div>
    )
}
