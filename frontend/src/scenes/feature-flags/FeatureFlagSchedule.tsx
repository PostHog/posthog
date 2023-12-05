import { LemonButton, LemonCheckbox, LemonDivider, LemonSelect, LemonTable } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DatePicker } from 'lib/components/DatePicker'
import { createdAtColumn, createdByColumn } from 'lib/lemon-ui/LemonTable/columnUtils'
import { useEffect } from 'react'

import { featureFlagLogic } from './featureFlagLogic'
import { FeatureFlagReleaseConditions } from './FeatureFlagReleaseConditions'

const logic = featureFlagLogic({ id: 'schedule' })
export const DAYJS_FORMAT = 'MMMM DD, YYYY h:mm A'

const columns = [createdByColumn() as any, createdAtColumn() as any]

export default function FeatureFlagSchedule(): JSX.Element {
    const { featureFlag, scheduledChanges, scheduleChangeType, scheduleDateMarker } = useValues(logic)
    const { setFeatureFlag, loadScheduledChanges, setScheduleDateMarker, setScheduleChangeType } = useActions(logic)

    useEffect(() => {
        loadScheduledChanges()
    }, [])

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
                        value={scheduleChangeType}
                        onChange={(value) => setScheduleChangeType(value)}
                        options={[
                            { label: 'Add a condition', value: 'add_condition' },
                            { label: 'Change status', value: 'change_status' },
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
                {scheduleChangeType === 'add_condition' && <FeatureFlagReleaseConditions usageContext="schedule" />}
                {scheduleChangeType === 'change_status' && (
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
                <div className="flex items-center justify-end">
                    <LemonButton type="primary">Schedule</LemonButton>
                </div>
                <LemonDivider className="" />
            </div>
            <LemonTable
                className="mt-8"
                loading={false}
                dataSource={scheduledChanges}
                columns={columns}
                emptyState="You do not have any scheduled changes"
            />
        </div>
    )
}
