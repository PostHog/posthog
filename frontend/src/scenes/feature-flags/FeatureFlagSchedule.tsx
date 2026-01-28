import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCalendarSelectInput,
    LemonCheckbox,
    LemonDivider,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
    LemonTag,
    LemonTagType,
    Link,
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors } from 'lib/utils'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { RecurrenceInterval, ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagVariantsForm } from './FeatureFlagVariantsForm'
import { groupFilters } from './FeatureFlags'
import { featureFlagLogic, validateFeatureFlagKey, variantKeyToIndexFeatureFlagPayloads } from './featureFlagLogic'

export const DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

function getScheduledVariantsPayloads(
    featureFlag: any,
    schedulePayload: any
): { variants: any[]; payloads: Record<string, any> } {
    const currentVariants = featureFlag.filters.multivariate?.variants || []
    const currentPayloads = featureFlag.filters.payloads || {}

    if (schedulePayload.variants && schedulePayload.variants.length > 0) {
        return {
            variants: schedulePayload.variants,
            payloads: schedulePayload.payloads || {},
        }
    }

    // If we have scheduled payloads but no variants, we're in the initial state after selecting UpdateVariants
    // Use the scheduled payloads (which should be properly transformed to index-based)
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

    const columns: LemonTableColumns<ScheduledChangeType> = [
        {
            title: 'Change',
            dataIndex: 'payload',
            render: function Render(_, scheduledChange: ScheduledChangeType) {
                const { payload } = scheduledChange

                if (payload.operation === ScheduledChangeOperationType.UpdateStatus) {
                    const isEnabled = payload.value
                    return (
                        <LemonTag type={isEnabled ? 'success' : 'default'} className="uppercase">
                            {isEnabled ? 'Enable' : 'Disable'}
                        </LemonTag>
                    )
                } else if (payload.operation === ScheduledChangeOperationType.AddReleaseCondition) {
                    const releaseText = groupFilters(payload.value, undefined, aggregationLabel)
                    return (
                        <div className="inline-flex leading-8">
                            <span className="mr-2">
                                <b>Add release condition:</b>
                            </span>
                            {typeof releaseText === 'string' && releaseText.startsWith('100% of') ? (
                                <LemonTag type="highlight">{releaseText}</LemonTag>
                            ) : (
                                releaseText
                            )}
                        </div>
                    )
                } else if (payload.operation === ScheduledChangeOperationType.UpdateVariants) {
                    const variantCount = payload.value?.variants?.length || 0
                    return (
                        <div className="inline-flex leading-8">
                            <span className="mr-2">
                                <b>Update variants:</b>
                            </span>
                            <LemonTag type="highlight">
                                {variantCount} variant{variantCount !== 1 ? 's' : ''}
                            </LemonTag>
                        </div>
                    )
                }

                return JSON.stringify(payload)
            },
        },
        {
            title: 'Scheduled at',
            dataIndex: 'scheduled_at',
            render: function Render(_, scheduledChange: ScheduledChangeType) {
                const scheduledAt = dayjs(scheduledChange.scheduled_at)
                const formattedDate = scheduledAt.format(DAYJS_FORMAT)
                const timeStr = scheduledAt.format('h:mm A')
                const isPaused = !scheduledChange.is_recurring && !!scheduledChange.recurrence_interval

                // Build recurring description for both active and paused recurring schedules
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
                            // For days 29-31, show "last day" since months vary in length
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

                    if (isPaused) {
                        // Paused: show pattern but indicate it won't run
                        return (
                            <Tooltip title={`Was: ${recurringDescription}. Resume to continue.`}>
                                <span className="text-muted">—</span>
                            </Tooltip>
                        )
                    }

                    // Active recurring: show pattern with next run in tooltip
                    const endDateStr = scheduledChange.end_date
                        ? `\nEnds: ${dayjs(scheduledChange.end_date).format('MMMM D, YYYY')}`
                        : ''
                    return (
                        <Tooltip title={`Next: ${formattedDate}${endDateStr}`}>
                            <span>{recurringDescription}</span>
                        </Tooltip>
                    )
                }
                return formattedDate
            },
        },
        {
            title: 'End date',
            dataIndex: 'end_date',
            render: function Render(_, scheduledChange: ScheduledChangeType) {
                if (!scheduledChange.is_recurring && !scheduledChange.recurrence_interval) {
                    // One-time schedule - no end date concept
                    return <span className="text-muted">—</span>
                }
                if (!scheduledChange.end_date) {
                    return <span className="text-muted">No end date</span>
                }
                return dayjs(scheduledChange.end_date).format('MMM D, YYYY')
            },
        },
        createdAtColumn() as LemonTableColumn<ScheduledChangeType, keyof ScheduledChangeType | undefined>,
        createdByColumn() as LemonTableColumn<ScheduledChangeType, keyof ScheduledChangeType | undefined>,
        {
            title: 'Status',
            dataIndex: 'executed_at',
            render: function Render(_, scheduledChange: ScheduledChangeType) {
                const { executed_at, failure_reason, is_recurring, recurrence_interval } = scheduledChange
                const isPaused = !is_recurring && !!recurrence_interval

                function getStatus(): { type: LemonTagType; text: string; tooltip?: string } {
                    if (failure_reason) {
                        return { type: 'danger', text: 'Error', tooltip: `Failed: ${failure_reason}` }
                    } else if (executed_at) {
                        return {
                            type: 'completion',
                            text: 'Complete',
                            tooltip: `Completed: ${dayjs(executed_at).format('MMMM D, YYYY h:mm A')}`,
                        }
                    } else if (isPaused) {
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
            },
        },
        {
            width: 0,
            render: function Render(_, scheduledChange: ScheduledChangeType) {
                return (
                    !scheduledChange.executed_at &&
                    featureFlag.can_edit && (
                        <More
                            overlay={
                                <>
                                    {scheduledChange.is_recurring && (
                                        <LemonButton
                                            onClick={() => stopRecurringScheduledChange(scheduledChange.id)}
                                            fullWidth
                                        >
                                            Pause recurring
                                        </LemonButton>
                                    )}
                                    {!scheduledChange.is_recurring && scheduledChange.recurrence_interval && (
                                        <LemonButton
                                            onClick={() => resumeRecurringScheduledChange(scheduledChange.id)}
                                            fullWidth
                                        >
                                            Resume recurring
                                        </LemonButton>
                                    )}
                                    <LemonButton
                                        status="danger"
                                        onClick={() => deleteScheduledChange(scheduledChange.id)}
                                        fullWidth
                                    >
                                        Delete scheduled change
                                    </LemonButton>
                                </>
                            }
                        />
                    )
                )
            },
        },
    ]

    return (
        <div>
            {featureFlag.can_edit ? (
                <div>
                    <h3 className="l3">Add a scheduled change</h3>
                    <div className="mb-6">Automatically change flag properties at a future point in time.</div>
                    <div className="flex flex-wrap gap-x-10 gap-y-4 mb-8">
                        <div>
                            <div className="font-semibold leading-6 h-6 mb-1">Change type</div>
                            <LemonSelect<ScheduledChangeOperationType>
                                className="w-50"
                                placeholder="Select variant"
                                value={scheduledChangeOperation}
                                onChange={(value) => value && setScheduledChangeOperation(value)}
                                options={[
                                    { label: 'Change status', value: ScheduledChangeOperationType.UpdateStatus },
                                    {
                                        label: 'Add a condition',
                                        value: ScheduledChangeOperationType.AddReleaseCondition,
                                    },
                                    ...(featureFlags[FEATURE_FLAGS.SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE] &&
                                    featureFlag.filters.multivariate
                                        ? [
                                              {
                                                  label: 'Update variants',
                                                  value: ScheduledChangeOperationType.UpdateVariants,
                                              },
                                          ]
                                        : []),
                                ]}
                            />
                        </div>
                        <div className="w-50">
                            <div className="font-semibold leading-6 h-6 mb-1">Date and time</div>
                            <LemonCalendarSelectInput
                                value={scheduleDateMarker}
                                onChange={(value) => setScheduleDateMarker(value)}
                                placeholder="Select date"
                                selectionPeriod="upcoming"
                                granularity="minute"
                            />
                        </div>
                        {scheduledChangeOperation === ScheduledChangeOperationType.UpdateStatus && (
                            <div>
                                <div className="font-semibold leading-6 h-6 mb-1">Repeat</div>
                                <div className="flex flex-col gap-2">
                                    <LemonCheckbox
                                        id="recurring-checkbox"
                                        label="Make recurring"
                                        onChange={(checked) => {
                                            setIsRecurring(checked)
                                            if (!checked) {
                                                setRecurrenceInterval(null)
                                                setEndDate(null)
                                            }
                                        }}
                                        checked={isRecurring}
                                    />
                                    <LemonSelect
                                        className="w-40"
                                        placeholder="Select interval"
                                        value={recurrenceInterval}
                                        onChange={setRecurrenceInterval}
                                        disabled={!isRecurring}
                                        options={[
                                            { value: RecurrenceInterval.Daily, label: 'Daily' },
                                            { value: RecurrenceInterval.Weekly, label: 'Weekly' },
                                            { value: RecurrenceInterval.Monthly, label: 'Monthly' },
                                            { value: RecurrenceInterval.Yearly, label: 'Yearly' },
                                        ]}
                                    />
                                </div>
                            </div>
                        )}
                        {isRecurring && (
                            <div className="w-50">
                                <div className="font-semibold leading-6 h-6 mb-1 flex items-center gap-1">
                                    End date (optional)
                                    <Tooltip
                                        title={
                                            <>
                                                Schedule will run through end of this day in the{' '}
                                                <Link to={urls.settings('project', 'date-and-time')} target="_blank">
                                                    project's timezone
                                                </Link>
                                            </>
                                        }
                                    >
                                        <IconInfo className="text-muted text-base" />
                                    </Tooltip>
                                </div>
                                <LemonCalendarSelectInput
                                    value={endDate}
                                    onChange={(value) => setEndDate(value)}
                                    placeholder="No end date"
                                    selectionPeriod="upcoming"
                                    granularity="day"
                                    clearable
                                />
                            </div>
                        )}
                    </div>

                    <div className="deprecated-space-y-4">
                        {scheduledChangeOperation === ScheduledChangeOperationType.UpdateStatus && (
                            <div className="border rounded p-4">
                                <LemonCheckbox
                                    id="flag-enabled-checkbox"
                                    label="Enable feature flag"
                                    onChange={(value) => {
                                        setSchedulePayload(null, value)
                                    }}
                                    checked={schedulePayload.active}
                                />
                            </div>
                        )}
                        {scheduledChangeOperation === ScheduledChangeOperationType.AddReleaseCondition && (
                            <FeatureFlagReleaseConditions
                                id={`schedule-release-conditions-${featureFlag.id}`}
                                filters={scheduleFilters}
                                onChange={(value, errors) => setSchedulePayload(value, null, errors, null, null)}
                                hideMatchOptions
                            />
                        )}
                        {scheduledChangeOperation === ScheduledChangeOperationType.UpdateVariants &&
                            featureFlags[FEATURE_FLAGS.SCHEDULE_FEATURE_FLAG_VARIANTS_UPDATE] &&
                            (() => {
                                return (
                                    <div className="border rounded p-4">
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
                                                let remainder = 100 - equalPercentage * currentVariants.length
                                                const distributedVariants = currentVariants.map((variant, index) => ({
                                                    ...variant,
                                                    rollout_percentage: equalPercentage + (index === 0 ? remainder : 0),
                                                }))
                                                setSchedulePayload(
                                                    null,
                                                    null,
                                                    null,
                                                    distributedVariants,
                                                    currentPayloads
                                                )
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
                                )
                            })()}
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
                                            : scheduledChangeOperation ===
                                                    ScheduledChangeOperationType.UpdateVariants &&
                                                variantErrors.some((error) => error.key != null)
                                              ? 'Fix schedule variant changes errors'
                                              : undefined
                                }
                            >
                                Schedule
                            </LemonButton>
                        </div>
                        <LemonDivider className="" />
                    </div>
                </div>
            ) : (
                <LemonBanner type="info" className="mb-2">
                    You don't have the necessary permissions to schedule changes to this flag. Contact your
                    administrator to request editing rights.
                </LemonBanner>
            )}
            <LemonTable
                rowClassName={(record) => (record.executed_at ? 'opacity-75' : '')}
                className="mt-4"
                loading={false}
                dataSource={scheduledChanges}
                columns={columns}
                defaultSorting={{
                    columnKey: 'scheduled_at',
                    order: 1,
                }}
                emptyState="You do not have any scheduled changes"
            />
        </div>
    )
}
