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
import { useActions, useValues } from 'kea'
import { dayjs } from 'lib/dayjs'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { hasFormErrors } from 'lib/utils'

import { groupsModel } from '~/models/groupsModel'
import { ScheduledChangeOperationType, ScheduledChangeType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'
import { groupFilters } from './FeatureFlags'

export const DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

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
                                onChange={(value, errors) => setSchedulePayload(value, null, errors)}
                                hideMatchOptions
                            />
                        )}
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
