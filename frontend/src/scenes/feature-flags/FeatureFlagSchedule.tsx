import { useActions, useValues } from 'kea'

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
} from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { hasFormErrors } from 'lib/utils'

import { groupsModel } from '~/models/groupsModel'
import { ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { FeatureFlagVariantsForm } from './FeatureFlagVariantsForm'
import { groupFilters } from './FeatureFlags'
import { featureFlagLogic, variantKeyToIndexFeatureFlagPayloads } from './featureFlagLogic'

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
    } = useValues(featureFlagLogic)
    const {
        deleteScheduledChange,
        setScheduleDateMarker,
        setSchedulePayload,
        setScheduledChangeOperation,
        createScheduledChange,
    } = useActions(featureFlagLogic)
    const { aggregationLabel } = useValues(groupsModel)
    const { featureFlags } = useValues(enabledFeaturesLogic)

    const aggregationGroupTypeIndex = featureFlag.filters.aggregation_group_type_index

    const scheduleFilters = { ...schedulePayload.filters, aggregation_group_type_index: aggregationGroupTypeIndex }

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
        atColumn('scheduled_at', 'Scheduled at') as LemonTableColumn<
            ScheduledChangeType,
            keyof ScheduledChangeType | undefined
        >,
        createdAtColumn() as LemonTableColumn<ScheduledChangeType, keyof ScheduledChangeType | undefined>,
        createdByColumn() as LemonTableColumn<ScheduledChangeType, keyof ScheduledChangeType | undefined>,
        {
            title: 'Status',
            dataIndex: 'executed_at',
            render: function Render(_, scheduledChange: ScheduledChangeType) {
                const { executed_at, failure_reason } = scheduledChange

                function getStatus(): { type: LemonTagType; text: string } {
                    if (failure_reason) {
                        return { type: 'danger', text: 'Error' }
                    } else if (executed_at) {
                        return { type: 'completion', text: 'Complete' }
                    }
                    return { type: 'default', text: 'Scheduled' }
                }
                const { type, text } = getStatus()
                return (
                    <Tooltip
                        title={
                            failure_reason
                                ? `Failed: ${failure_reason}`
                                : executed_at && `Completed: ${dayjs(executed_at).format('MMMM D, YYYY h:mm A')}`
                        }
                    >
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
                                <LemonButton
                                    status="danger"
                                    onClick={() => deleteScheduledChange(scheduledChange.id)}
                                    fullWidth
                                >
                                    Delete scheduled change
                                </LemonButton>
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
                    <div className="inline-flex gap-10 mb-8">
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
                    </div>

                    <div className="deprecated-space-y-4">
                        {scheduledChangeOperation === ScheduledChangeOperationType.UpdateStatus && (
                            <>
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
                            </>
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
                                const { variants: displayVariants, payloads: displayPayloads } =
                                    getScheduledVariantsPayloads(featureFlag, schedulePayload)

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
                                        : hasFormErrors(schedulePayloadErrors)
                                          ? 'Fix release condition errors'
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
