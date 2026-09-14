import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { DataQualityScheduleLogicProps, dataQualityScheduleLogic } from './dataQualityScheduleLogic'
import { DataQualityScheduleIntervalEnumApi } from './generated/api.schemas'

export function DataQualitySchedule(props: DataQualityScheduleLogicProps): JSX.Element {
    const { schedule, scheduleLoading, scheduleError } = useValues(dataQualityScheduleLogic(props))
    const { loadSchedule, updateSchedule } = useActions(dataQualityScheduleLogic(props))

    if (!schedule) {
        return scheduleError ? (
            <LemonBanner type="error" action={{ children: 'Retry', onClick: loadSchedule }}>
                Could not load the check schedule. Try again.
            </LemonBanner>
        ) : (
            <Spinner />
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center flex-wrap gap-2">
                <LemonSwitch
                    checked={schedule.enabled}
                    onChange={(enabled) => updateSchedule({ enabled })}
                    disabled={scheduleLoading || !!scheduleError?.uncertain}
                    label="Run automatically"
                    data-attr="data-quality-schedule-enabled"
                />
                <LemonSelect
                    value={schedule.interval}
                    disabledReason={
                        scheduleLoading
                            ? 'Saving schedule'
                            : scheduleError?.uncertain
                              ? 'Reload the schedule to try again'
                              : undefined
                    }
                    onChange={(interval) => updateSchedule({ interval })}
                    size="small"
                    data-attr="data-quality-schedule-interval"
                    options={[
                        { value: DataQualityScheduleIntervalEnumApi['1hour'], label: 'Every hour' },
                        { value: DataQualityScheduleIntervalEnumApi['6hour'], label: 'Every 6 hours' },
                        { value: DataQualityScheduleIntervalEnumApi['12hour'], label: 'Every 12 hours' },
                        { value: DataQualityScheduleIntervalEnumApi['24hour'], label: 'Daily' },
                        { value: DataQualityScheduleIntervalEnumApi['7day'], label: 'Weekly' },
                    ]}
                />
                {scheduleLoading ? (
                    <Spinner />
                ) : (
                    schedule.enabled &&
                    schedule.next_run_at && (
                        <span className="text-secondary text-sm">
                            Next run <TZLabel time={schedule.next_run_at} />
                        </span>
                    )
                )}
            </div>
            {scheduleError &&
                (scheduleError.uncertain ? (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Reload', onClick: loadSchedule, loading: scheduleLoading }}
                    >
                        Could not confirm the schedule update. Reload it before trying again.
                    </LemonBanner>
                ) : (
                    <LemonBanner type="error">{scheduleError.message}</LemonBanner>
                ))}
        </div>
    )
}
