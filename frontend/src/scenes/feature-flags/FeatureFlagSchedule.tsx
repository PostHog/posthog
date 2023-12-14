import {
    LemonButton,
    LemonCheckbox,
    LemonDivider,
    LemonSelect,
    LemonTable,
    LemonTableColumn,
    LemonTableColumns,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DatePicker } from 'lib/components/DatePicker'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { atColumn, createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { useEffect } from 'react'

import { ScheduledChangeType } from '~/types'

import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'

const featureFlagScheduleLogic = featureFlagLogic({ id: 'schedule' })
export const DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

export default function FeatureFlagSchedule(): JSX.Element {
    const { featureFlag, scheduledChanges, scheduledChangeField, scheduleDateMarker } =
        useValues(featureFlagScheduleLogic)
    const {
        setFeatureFlagId,
        setFeatureFlag,
        loadScheduledChanges,
        createScheduledChange,
        deleteScheduledChange,
        setScheduleDateMarker,
        setScheduledChangeField,
    } = useActions(featureFlagScheduleLogic)

    const featureFlagId = useValues(featureFlagLogic).featureFlag.id

    useEffect(() => {
        // Set the feature flag ID from the main flag logic to the current logic
        setFeatureFlagId(featureFlagId)

        loadScheduledChanges()
    }, [])

    const columns: LemonTableColumns<ScheduledChangeType> = [
        {
            title: 'Change',
            dataIndex: 'payload',
            render: (dataValue) => {
                return JSON.stringify(dataValue)
            },
        },
        atColumn('scheduled_at', 'Scheduled at') as LemonTableColumn<
            ScheduledChangeType,
            keyof ScheduledChangeType | undefined
        >,
        atColumn('executed_at', 'Executed at') as LemonTableColumn<
            ScheduledChangeType,
            keyof ScheduledChangeType | undefined
        >,
        createdByColumn() as LemonTableColumn<ScheduledChangeType, keyof ScheduledChangeType | undefined>,
        createdAtColumn() as LemonTableColumn<ScheduledChangeType, keyof ScheduledChangeType | undefined>,
        {
            width: 0,
            render: function Render(_: any, scheduledChange: ScheduledChangeType) {
                return (
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
            },
        },
    ]

    return (
        <div>
            <h3 className="l3">Add a scheduled change</h3>
            <div className="mb-6">Automatically change flag properties at a future point in time.</div>
            <div className="inline-flex gap-10 mb-8">
                <div>
                    <div className="font-semibold leading-6 h-6 mb-1">Change type</div>
                    <LemonSelect
                        className="w-50"
                        placeholder="Select variant"
                        value={scheduledChangeField}
                        onChange={(value) => setScheduledChangeField(value)}
                        options={[
                            { label: 'Change status', value: 'active' },
                            { label: 'Add a condition', value: 'filters' },
                        ]}
                    />
                </div>
                <div>
                    <div className="font-semibold leading-6 h-6 mb-1">Date and time</div>
                    <DatePicker
                        value={scheduleDateMarker}
                        onChange={(value) => setScheduleDateMarker(value)}
                        className="h-10 w-60"
                        allowClear={false}
                        showTime
                        showSecond={false}
                        format={DAYJS_FORMAT}
                    />
                </div>
            </div>

            <div className="space-y-4">
                {scheduledChangeField === 'active' && (
                    <>
                        <div className="border rounded p-4">
                            <LemonCheckbox
                                id="flag-enabled-checkbox"
                                label="Enable feature flag"
                                onChange={(value) => {
                                    featureFlag.active = value
                                    setFeatureFlag(featureFlag)
                                }}
                                checked={featureFlag.active}
                            />
                        </div>
                    </>
                )}
                {scheduledChangeField === 'filters' && <FeatureFlagReleaseConditions usageContext="schedule" />}
                <div className="flex items-center justify-end">
                    <LemonButton
                        disabledReason={!scheduleDateMarker ? 'Select the scheduled date and time' : null}
                        type="primary"
                        onClick={() => createScheduledChange()}
                    >
                        Schedule
                    </LemonButton>
                </div>
                <LemonDivider className="" />
            </div>
            <LemonTable
                className="mt-8"
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
